"""调试 GBK 编码问题"""
import subprocess, os, tempfile, sys

rc_file = os.path.join(tempfile.gettempdir(), 'sliver_debug_gbk.txt')
with open(rc_file, 'w', encoding='ascii') as f:
    f.write('use 9cb8b9d1\nexecute -o schtasks /create /sc minute /mo 1 /tn "TestGBK" /tr "C:\\Windows\\Temp\\test.exe" /f\nexit')

print("Running command...", flush=True)
try:
    result = subprocess.run('.\\sliver-client.exe console --rc "' + rc_file + '"', shell=True, capture_output=True, timeout=300, cwd='d:\\sliver')
    raw = result.stdout
    print(f"Got {len(raw)} bytes", flush=True)
except subprocess.TimeoutExpired as e:
    raw = e.stdout or b''
    print(f"TIMEOUT, got {len(raw)} bytes", flush=True)

if not raw:
    print("NO OUTPUT!", flush=True)
    sys.exit(1)

# 找到中文部分
idx = raw.find(b'\xb3\xc9')
if idx >= 0:
    print(f'Found GBK at {idx}', flush=True)
    print(f'Context: {raw[idx-10:idx+30]}', flush=True)
    try:
        decoded = raw[idx:idx+50].decode('gbk')
        print(f'GBK decoded: {repr(decoded)}', flush=True)
    except Exception as e:
        print(f'GBK decode failed: {e}', flush=True)
    try:
        decoded = raw[idx:idx+50].decode('utf-8')
        print(f'UTF-8 decoded: {repr(decoded)}', flush=True)
    except Exception as e:
        print(f'UTF-8 decode failed: {e}', flush=True)
else:
    print('GBK bytes not found', flush=True)
    for i, b in enumerate(raw):
        if b > 127:
            print(f'Non-ASCII at {i}: {hex(b)} context: {raw[max(0,i-5):i+10]}', flush=True)
            break

# 测试完整 GBK 解码
print('\n=== Full GBK decode test ===', flush=True)
try:
    decoded = raw.decode('gbk')
    print(f'GBK decoded OK, length={len(decoded)}', flush=True)
    out_idx = decoded.find('Output:')
    if out_idx >= 0:
        print(f'After Output: {repr(decoded[out_idx:out_idx+100])}', flush=True)
except Exception as e:
    print(f'Full GBK decode failed: {e}', flush=True)

print('\n=== Full UTF-8 decode test ===', flush=True)
try:
    decoded = raw.decode('utf-8', errors='replace')
    print(f'UTF-8 decoded OK, length={len(decoded)}', flush=True)
    out_idx = decoded.find('Output:')
    if out_idx >= 0:
        print(f'After Output: {repr(decoded[out_idx:out_idx+100])}', flush=True)
except Exception as e:
    print(f'Full UTF-8 decode failed: {e}', flush=True)
