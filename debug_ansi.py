"""调试 ANSI 转义码清理"""
import subprocess, os, tempfile, re, sys

rc_file = os.path.join(tempfile.gettempdir(), 'sliver_debug_ansi.txt')
with open(rc_file, 'w', encoding='ascii') as f:
    f.write('use 9cb8b9d1\nregistry write --hive HKCU --type string "Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Test123" "C:\\Windows\\Temp\\test.exe"\nexit')

print(f"Running command...", flush=True)
try:
    result = subprocess.run('.\\sliver-client.exe console --rc "' + rc_file + '"', shell=True, capture_output=True, timeout=180, cwd='d:\\sliver')
    raw = result.stdout
    print(f"Got {len(raw)} bytes", flush=True)
except subprocess.TimeoutExpired as e:
    raw = e.stdout or b''
    print(f"TIMEOUT, got {len(raw)} bytes", flush=True)

if not raw:
    print("NO OUTPUT!", flush=True)
    sys.exit(1)

# 显示原始字节
print("=== RAW BYTES (first 800) ===", flush=True)
print(raw[:800], flush=True)
print("=== REPR ===", flush=True)
print(repr(raw[:800]), flush=True)

# 测试清理
text = raw.decode('utf-8', errors='replace')
print("=== DECODED TEXT (first 800) ===", flush=True)
print(text[:800], flush=True)

# 测试 ANSI 清理
cleaned = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
print("=== AFTER ANSI CLEAN (first 800) ===", flush=True)
print(cleaned[:800], flush=True)

# 测试 spinner 行清理
lines = cleaned.split('\n')
cleaned_lines = []
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped and stripped[0] in '|/\\-':
        print(f"  REMOVED line {i}: {repr(stripped[:50])}", flush=True)
        continue
    cleaned_lines.append(line)
result_text = '\n'.join(cleaned_lines)
print("=== FINAL RESULT ===", flush=True)
print(result_text[:800], flush=True)
