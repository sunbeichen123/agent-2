import subprocess, tempfile, os

session_id = "03d96202"
rc_file = os.path.join(tempfile.gettempdir(), 'sliver_rc.txt')

# Test: execute a simple PowerShell command with - flag to verify -- separator fix
# If the fix works, this should NOT produce the "inationPath" error
ps_test = 'powershell -ExecutionPolicy Bypass -Command "Get-Process -Name explorer | Select-Object -Property Name,Id | ConvertTo-Json"'

with open(rc_file, 'w', encoding='ascii') as f:
    f.write("use %s\nexecute -o -- %s\nexit" % (session_id, ps_test))

result = subprocess.run(['.\\sliver-client.exe', 'console', '--rc', rc_file], 
                       capture_output=True, timeout=30, cwd='d:\\sliver')
stdout = result.stdout.decode('utf-8', errors='replace')
print("=== Test with -- separator ===")
print(stdout[:1000])

# Now test WITHOUT -- separator to show the old bug
ps_test2 = 'powershell -ExecutionPolicy Bypass -Command "Get-Process -Name explorer | Select-Object -Property Name,Id | ConvertTo-Json"'

with open(rc_file, 'w', encoding='ascii') as f:
    f.write("use %s\nexecute -o %s\nexit" % (session_id, ps_test2))

result = subprocess.run(['.\\sliver-client.exe', 'console', '--rc', rc_file], 
                       capture_output=True, timeout=30, cwd='d:\\sliver')
stdout = result.stdout.decode('utf-8', errors='replace')
print("=== Test WITHOUT -- separator ===")
print(stdout[:1000])

os.remove(rc_file)
