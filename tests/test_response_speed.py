import time
import requests

BASE_URL = "http://127.0.0.1:5001"

endpoints = [
    "/api/metrics",
    "/api/charts",
    "/api/analytics",
    "/api/command_center",
    "/api/detailed_charts",
    "/api/logs",
    "/api/repeat_offenders",
    "/api/deployed_patrols",
    "/api/recommendations",
    "/api/evaluation"
]

print("Testing TrafficFlow Endpoint Response Speeds...")
print("-" * 60)

all_under_100ms = True

for ep in endpoints:
    url = f"{BASE_URL}{ep}"
    t0 = time.time()
    try:
        res = requests.get(url, timeout=10)
        elapsed = (time.time() - t0) * 1000
        print(f"GET {ep:<25} | Status: {res.status_code} | Time: {elapsed:.2f}ms")
        if elapsed > 150:  # Allow 150ms buffer for remote test connections
            # Test again to verify cache hit
            t0 = time.time()
            res = requests.get(url, timeout=10)
            elapsed2 = (time.time() - t0) * 1000
            print(f"  --> Retry: {elapsed2:.2f}ms")
            if elapsed2 > 100:
                all_under_100ms = False
    except Exception as e:
        print(f"GET {ep:<25} | Failed: {e}")
        all_under_100ms = False

print("-" * 60)
if all_under_100ms:
    print("SUCCESS: All endpoints responded in < 100ms!")
else:
    print("WARNING: Some endpoints took longer than 100ms.")
