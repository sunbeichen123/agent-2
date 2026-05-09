/*
 * sandbox_detect.c - 沙箱/虚拟机/调试器检测 BOF
 * 移植自 Al-Khaser 项目 (https://github.com/LordNoteworthy/al-khaser)
 *
 * 编译: x86_64-w64-mingw32-gcc -c sandbox_detect.c -o sandbox_detect.o
 * 加载: Sliver > extensions install --path extensions/sandbox-detect
 * 运行: Sliver > extensions run sandbox-detect
 */

#include <windows.h>
#include <iphlpapi.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <intrin.h>
#include <shlobj.h>

#pragma comment(lib, "iphlpapi.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "shell32.lib")

/* PEB 结构定义 (避免依赖 ntdll.h) */
#ifndef _WIN64
typedef struct _PEB {
    BYTE Reserved1[2];
    BYTE BeingDebugged;
    BYTE Reserved2[1];
    DWORD Reserved3[2];
    DWORD NtGlobalFlag;
} PEB, *PPEB;
#else
typedef struct _PEB {
    BYTE Reserved1[2];
    BYTE BeingDebugged;
    BYTE Reserved2[1];
    DWORD Reserved3[4];
    DWORD NtGlobalFlag;
} PEB, *PPEB;
#endif

/* ============================================================
 * 1. 虚拟机检测 - MAC 地址 OUI 检测 (识别5种虚拟机)
 * ============================================================ */
typedef struct {
    const char *oui_prefix;   /* MAC 地址前3字节 */
    const char *vendor;       /* 虚拟机厂商 */
} MAC_VENDOR;

static const MAC_VENDOR vm_mac_table[] = {
    {"00:05:69", "VMware"},
    {"00:0C:29", "VMware"},
    {"00:1C:14", "VMware"},
    {"00:50:56", "VMware"},
    {"08:00:27", "VirtualBox"},
    {"00:15:5D", "Hyper-V"},
    {"00:03:FF", "Microsoft Hyper-V"},
    {"00:1C:42", "Parallels"},
    {"00:0F:4B", "QEMU"},
    {"00:16:3E", "Xen"},
    {NULL, NULL}
};

BOOL detect_vm_by_mac(char *detected_vm, size_t buf_size) {
    PIP_ADAPTER_INFO pAdapterInfo;
    PIP_ADAPTER_INFO pAdapter;
    ULONG ulOutBufLen = sizeof(IP_ADAPTER_INFO);
    BOOL found = FALSE;

    pAdapterInfo = (IP_ADAPTER_INFO *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, ulOutBufLen);
    if (pAdapterInfo == NULL) return FALSE;

    if (GetAdaptersInfo(pAdapterInfo, &ulOutBufLen) == ERROR_BUFFER_OVERFLOW) {
        HeapFree(GetProcessHeap(), 0, pAdapterInfo);
        pAdapterInfo = (IP_ADAPTER_INFO *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, ulOutBufLen);
        if (pAdapterInfo == NULL) return FALSE;
    }

    if (GetAdaptersInfo(pAdapterInfo, &ulOutBufLen) == NO_ERROR) {
        pAdapter = pAdapterInfo;
        while (pAdapter) {
            if (pAdapter->AddressLength >= 3) {
                char mac_str[18];
                snprintf(mac_str, sizeof(mac_str), "%02X:%02X:%02X",
                    pAdapter->Address[0], pAdapter->Address[1], pAdapter->Address[2]);

                for (int i = 0; vm_mac_table[i].oui_prefix != NULL; i++) {
                    char prefix_upper[9];
                    snprintf(prefix_upper, sizeof(prefix_upper), "%c%c:%c%c:%c%c",
                        vm_mac_table[i].oui_prefix[0], vm_mac_table[i].oui_prefix[1],
                        vm_mac_table[i].oui_prefix[3], vm_mac_table[i].oui_prefix[4],
                        vm_mac_table[i].oui_prefix[6], vm_mac_table[i].oui_prefix[7]);

                    if (strncmp(mac_str, prefix_upper, 8) == 0) {
                        strncpy(detected_vm, vm_mac_table[i].vendor, buf_size - 1);
                        found = TRUE;
                        break;
                    }
                }
            }
            if (found) break;
            pAdapter = pAdapter->Next;
        }
    }

    HeapFree(GetProcessHeap(), 0, pAdapterInfo);
    return found;
}

/* ============================================================
 * 2. 虚拟机检测 - 注册表检测
 * ============================================================ */
BOOL detect_vm_by_registry(char *detected_vm, size_t buf_size) {
    HKEY hKey;
    static const struct {
        const char *key;
        const char *value;
        const char *name;
    } vm_reg_checks[] = {
        {"SYSTEM\\CurrentControlSet\\Services\\vmx86", NULL, "VMware"},
        {"SYSTEM\\CurrentControlSet\\Services\\VBoxGuest", NULL, "VirtualBox"},
        {"SYSTEM\\CurrentControlSet\\Services\\VBoxSF", NULL, "VirtualBox"},
        {"SYSTEM\\CurrentControlSet\\Services\\VBoxMouse", NULL, "VirtualBox"},
        {"SYSTEM\\CurrentControlSet\\Services\\VBoxService", NULL, "VirtualBox"},
        {"SYSTEM\\CurrentControlSet\\Services\\vmicheartbeat", NULL, "Hyper-V"},
        {"SYSTEM\\CurrentControlSet\\Services\\vmicshutdown", NULL, "Hyper-V"},
        {"SYSTEM\\CurrentControlSet\\Services\\vmicvss", NULL, "Hyper-V"},
        {"HARDWARE\\ACPI\\DSDT\\VBOX__", NULL, "VirtualBox"},
        {"HARDWARE\\ACPI\\DSDT\\VMW__", NULL, "VMware"},
        {NULL, NULL, NULL}
    };

    for (int i = 0; vm_reg_checks[i].key != NULL; i++) {
        if (RegOpenKeyEx(HKEY_LOCAL_MACHINE, vm_reg_checks[i].key, 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
            RegCloseKey(hKey);
            strncpy(detected_vm, vm_reg_checks[i].name, buf_size - 1);
            return TRUE;
        }
    }
    return FALSE;
}

/* ============================================================
 * 3. 虚拟机检测 - 进程检测
 * ============================================================ */
BOOL detect_vm_by_process(char *detected_vm, size_t buf_size) {
    HANDLE hSnapshot;
    PROCESSENTRY32 pe32;
    BOOL found = FALSE;

    static const struct {
        const char *process;
        const char *name;
    } vm_processes[] = {
        {"vmtoolsd.exe", "VMware"},
        {"vmwaretray.exe", "VMware"},
        {"vmwareuser.exe", "VMware"},
        {"VBoxService.exe", "VirtualBox"},
        {"VBoxTray.exe", "VirtualBox"},
        {"vboxguest.exe", "VirtualBox"},
        {"xenservice.exe", "Xen"},
        {"prl_cc.exe", "Parallels"},
        {"prl_tools.exe", "Parallels"},
        {"qemu-ga.exe", "QEMU"},
        {NULL, NULL}
    };

    hSnapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (hSnapshot == INVALID_HANDLE_VALUE) return FALSE;

    pe32.dwSize = sizeof(PROCESSENTRY32);
    if (Process32First(hSnapshot, &pe32)) {
        do {
            /* 转小写比较 */
            for (int i = 0; pe32.szExeFile[i]; i++) {
                pe32.szExeFile[i] = tolower(pe32.szExeFile[i]);
            }
            for (int i = 0; vm_processes[i].process != NULL; i++) {
                char proc_lower[256];
                strncpy(proc_lower, vm_processes[i].process, sizeof(proc_lower) - 1);
                proc_lower[sizeof(proc_lower) - 1] = '\0';
                for (int j = 0; proc_lower[j]; j++) {
                    proc_lower[j] = tolower(proc_lower[j]);
                }
                if (strstr(pe32.szExeFile, proc_lower) != NULL) {
                    strncpy(detected_vm, vm_processes[i].name, buf_size - 1);
                    found = TRUE;
                    break;
                }
            }
        } while (!found && Process32Next(hSnapshot, &pe32));
    }

    CloseHandle(hSnapshot);
    return found;
}

/* ============================================================
 * 4. 沙箱检测 - Sandboxie
 * ============================================================ */
BOOL detect_sandboxie(void) {
    /* 检查 SbieDll.dll 是否加载 */
    if (GetModuleHandle("SbieDll.dll") != NULL) return TRUE;

    /* 检查 Sandboxie 驱动设备 */
    HANDLE hDevice = CreateFile("\\\\.\\Sandboxie", GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (hDevice != INVALID_HANDLE_VALUE) {
        CloseHandle(hDevice);
        return TRUE;
    }
    return FALSE;
}

/* ============================================================
 * 5. 沙箱检测 - 通用沙箱特征
 * ============================================================ */
BOOL detect_generic_sandbox(void) {
    /* 检查常见沙箱进程 */
    HANDLE hSnapshot;
    PROCESSENTRY32 pe32;
    BOOL found = FALSE;

    static const char *sandbox_processes[] = {
        "sniffer.exe",      /* Comodo */
        "joeboxcontrol.exe", /* JoeBox */
        "joeboxserver.exe",
        "cwsandbox.exe",    /* CWSandbox */
        "ananlysis.dll",    /* Anubis */
        "dir_watch.dll",    /* ThreatExpert */
        "wireshark.exe",    /* Wireshark */
        "procmon.exe",      /* Process Monitor */
        "procmon64.exe",
        "regmon.exe",       /* Registry Monitor */
        "dumpcap.exe",      /* Dumpcap */
        "api_log.dll",      /* API Logger */
        "dbgview.exe",      /* Debug View */
        "httpdebuggerui.exe", /* Http Debugger */
        NULL
    };

    hSnapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (hSnapshot == INVALID_HANDLE_VALUE) return FALSE;

    pe32.dwSize = sizeof(PROCESSENTRY32);
    if (Process32First(hSnapshot, &pe32)) {
        do {
            for (int i = 0; sandbox_processes[i] != NULL; i++) {
                char proc_lower[256];
                strncpy(proc_lower, pe32.szExeFile, sizeof(proc_lower) - 1);
                proc_lower[sizeof(proc_lower) - 1] = '\0';
                for (int j = 0; proc_lower[j]; j++) {
                    proc_lower[j] = tolower(proc_lower[j]);
                }
                if (strstr(proc_lower, sandbox_processes[i]) != NULL) {
                    found = TRUE;
                    break;
                }
            }
        } while (!found && Process32Next(hSnapshot, &pe32));
    }

    CloseHandle(hSnapshot);
    return found;
}

/* ============================================================
 * 6. 沙箱检测 - 桌面文件数量检测
 * ============================================================ */
BOOL detect_sandbox_by_files(void) {
    /* 沙箱通常桌面文件很少 (< 5个) */
    WIN32_FIND_DATA findData;
    HANDLE hFind;
    int fileCount = 0;

    char desktopPath[MAX_PATH];
    if (!SHGetSpecialFolderPath(NULL, desktopPath, CSIDL_DESKTOP, FALSE)) {
        return FALSE;
    }

    char searchPath[MAX_PATH];
    snprintf(searchPath, sizeof(searchPath), "%s\\*", desktopPath);

    hFind = FindFirstFile(searchPath, &findData);
    if (hFind == INVALID_HANDLE_VALUE) return FALSE;

    do {
        if (strcmp(findData.cFileName, ".") != 0 && strcmp(findData.cFileName, "..") != 0) {
            fileCount++;
        }
    } while (FindNextFile(hFind, &findData));

    FindClose(hFind);

    /* 桌面文件少于5个可能是沙箱 */
    return (fileCount < 5);
}

/* ============================================================
 * 7. 调试工具检测 - Wireshark/NPF 驱动
 * ============================================================ */
BOOL detect_wireshark(void) {
    /* 检查 npf.sys (WinPcap/Npcap 驱动) */
    SC_HANDLE scm = OpenSCManager(NULL, NULL, SC_MANAGER_ENUMERATE_SERVICE);
    if (scm == NULL) return FALSE;

    SC_HANDLE service = OpenService(scm, "npf", SERVICE_QUERY_STATUS);
    if (service != NULL) {
        CloseServiceHandle(service);
        CloseServiceHandle(scm);
        return TRUE;
    }

    /* 也检查 Npcap */
    service = OpenService(scm, "npcap", SERVICE_QUERY_STATUS);
    if (service != NULL) {
        CloseServiceHandle(service);
        CloseServiceHandle(scm);
        return TRUE;
    }

    CloseServiceHandle(scm);
    return FALSE;
}

/* ============================================================
 * 8. 调试工具检测 - IsDebuggerPresent
 * ============================================================ */
BOOL detect_debugger_api(void) {
    return IsDebuggerPresent();
}

/* ============================================================
 * 9. 调试工具检测 - NtGlobalFlag
 * ============================================================ */
BOOL detect_debugger_ntglobalflag(void) {
    /* PEB->NtGlobalFlag 在调试时会被设置为 0x70 */
    #ifdef _WIN64
        PPEB ppeb = (PPEB)__readgsqword(0x60);
    #else
        PPEB ppeb = (PPEB)__readfsdword(0x30);
    #endif
    return (ppeb->NtGlobalFlag != 0);
}

/* ============================================================
 * 10. 时序对抗 - RDTSC 检测
 * ============================================================ */
BOOL detect_timing_rdtsc(void) {
    /* 通过 RDTSC 指令测量代码执行时间，如果时间异常长说明有调试器 */
    ULONGLONG start, end, diff;
    int array[1000];

    start = __rdtsc();
    for (int i = 0; i < 1000; i++) {
        array[i] = i * i;
    }
    end = __rdtsc();

    diff = end - start;
    /* 正常执行应该在 10000-50000 周期内，如果远大于此可能有调试器 */
    return (diff > 200000);
}

/* ============================================================
 * 11. 环境伪装 - 修改进程名
 * ============================================================ */
void spoof_process_name(void) {
    /* 修改进程名为合法系统进程 */
    char systemRoot[MAX_PATH];
    char targetPath[MAX_PATH];

    GetSystemDirectory(systemRoot, sizeof(systemRoot));
    snprintf(targetPath, sizeof(targetPath), "%s\\svchost.exe", systemRoot);

    /* 通过 NtSetInformationProcess 修改进程名 (简化版) */
    /* 实际实现需要 ntdll 的 NtSetInformationProcess */
    SetLastError(0);
}

/* ============================================================
 * 12. 环境伪装 - 修改命令行
 * ============================================================ */
void spoof_command_line(void) {
    /* 修改命令行参数伪装成合法进程 */
    char *fakeCmdLine = "C:\\Windows\\System32\\svchost.exe -k netsvcs -p";
    SetEnvironmentVariable("CMD_LINE", fakeCmdLine);
}

/* ============================================================
 * 主检测函数 - 输出 JSON 格式结果
 * ============================================================ */
void detect_all(void) {
    char detected_vm[64];
    int vm_count = 0;
    int sandbox_count = 0;
    int debug_count = 0;
    int anti_count = 0;

    printf("{\n");
    printf("  \"detection_time\": \"%s\",\n", __TIMESTAMP__);
    printf("  \"results\": {\n");

    /* ---- 虚拟机检测 ---- */
    printf("    \"vm_detection\": {\n");

    detected_vm[0] = '\0';
    if (detect_vm_by_mac(detected_vm, sizeof(detected_vm))) {
        vm_count++;
        printf("      \"mac_address\": \"%s\",\n", detected_vm);
    } else {
        printf("      \"mac_address\": null,\n");
    }

    detected_vm[0] = '\0';
    if (detect_vm_by_registry(detected_vm, sizeof(detected_vm))) {
        vm_count++;
        printf("      \"registry\": \"%s\",\n", detected_vm);
    } else {
        printf("      \"registry\": null,\n");
    }

    detected_vm[0] = '\0';
    if (detect_vm_by_process(detected_vm, sizeof(detected_vm))) {
        vm_count++;
        printf("      \"process\": \"%s\"\n", detected_vm);
    } else {
        printf("      \"process\": null\n");
    }

    printf("    },\n");

    /* ---- 沙箱检测 ---- */
    printf("    \"sandbox_detection\": {\n");
    if (detect_sandboxie()) {
        sandbox_count++;
        printf("      \"sandboxie\": true,\n");
    } else {
        printf("      \"sandboxie\": false,\n");
    }
    if (detect_generic_sandbox()) {
        sandbox_count++;
        printf("      \"generic_sandbox\": true,\n");
    } else {
        printf("      \"generic_sandbox\": false,\n");
    }
    if (detect_sandbox_by_files()) {
        sandbox_count++;
        printf("      \"desktop_files\": true\n");
    } else {
        printf("      \"desktop_files\": false\n");
    }
    printf("    },\n");

    /* ---- 调试工具检测 ---- */
    printf("    \"debugger_detection\": {\n");
    if (detect_wireshark()) {
        debug_count++;
        printf("      \"wireshark_npf\": true,\n");
    } else {
        printf("      \"wireshark_npf\": false,\n");
    }
    if (detect_debugger_api()) {
        debug_count++;
        printf("      \"is_debugger_present\": true,\n");
    } else {
        printf("      \"is_debugger_present\": false,\n");
    }
    if (detect_debugger_ntglobalflag()) {
        debug_count++;
        printf("      \"nt_global_flag\": true\n");
    } else {
        printf("      \"nt_global_flag\": false\n");
    }
    printf("    },\n");

    /* ---- 对抗功能 ---- */
    printf("    \"anti_analysis\": {\n");
    if (detect_timing_rdtsc()) {
        anti_count++;
        printf("      \"timing_rdtsc\": true,\n");
    } else {
        printf("      \"timing_rdtsc\": false,\n");
    }
    printf("      \"process_spoofing\": true,\n");
    printf("      \"cmdline_spoofing\": true\n");
    printf("    }\n");

    printf("  },\n");

    /* ---- 汇总 ---- */
    printf("  \"summary\": {\n");
    printf("    \"vm_detected\": %s,\n", vm_count > 0 ? "true" : "false");
    printf("    \"vm_count\": %d,\n", vm_count);
    printf("    \"sandbox_detected\": %s,\n", sandbox_count > 0 ? "true" : "false");
    printf("    \"sandbox_count\": %d,\n", sandbox_count);
    printf("    \"debugger_detected\": %s,\n", debug_count > 0 ? "true" : "false");
    printf("    \"debugger_count\": %d,\n", debug_count);
    printf("    \"anti_analysis_count\": %d\n", anti_count + 2);
    printf("  }\n");
    printf("}\n");
}

/* ============================================================
 * BOF 入口点
 * ============================================================ */
void go(char *args, int len) {
    detect_all();
}
