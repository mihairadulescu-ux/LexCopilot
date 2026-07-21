import os
import sys
import time
import subprocess
import requests

URL_JUST = "https://legislatie.just.ro/api/Search/GetLegi"
PAYLOAD = '{"SearchAn":"1990","NumarPagina":1,"RezultatePagina":10}'

def test_curl_sistem():
    print("\n🧪 [Diagnostic 1] Testare cu comanda `curl` din sistem (Linux)...", flush=True)
    cmd = [
        "curl", "-v", "-X", "POST", URL_JUST,
        "-H", "Content-Type: application/json",
        "-d", PAYLOAD,
        "--connect-timeout", "10"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        print(f"📋 Exit Code curl: {res.returncode}", flush=True)
        print(f"📄 Output (STDOUT/STDERR):\n{res.stderr[:1000]}", flush=True)
        if res.stdout:
            print(f"✅ Răspuns primit ({len(res.stdout)} octeți):\n{res.stdout[:300]}", flush=True)
    except Exception as e:
        print(f"❌ Subprocess error: {e}", flush=True)

def test_requests_cu_retry():
    print("\n🧪 [Diagnostic 2] Testare cu `requests` și pauze de pauză (Retry Loop)...", flush=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json"
    }
    for i in range(1, 4):
        print(f"   └─ Încercarea {i}...", flush=True)
        try:
            r = requests.post(URL_JUST, data=PAYLOAD, headers=headers, timeout=15)
            print(f"   ✅ HTTP Status: {r.status_code}, Lungime: {len(r.text)}", flush=True)
            if r.status_code == 200:
                print(f"   📄 Fragment: {r.text[:200]}", flush=True)
                break
        except Exception as e:
            print(f"   ⚠️ Eroare: {e}", flush=True)
            time.sleep(3 * i)

if __name__ == "__main__":
    print("============================================================", flush=True)
    print("🚀 DIAGNOSTIC DETALIAT CONEXIUNE JUST.RO", flush=True)
    print("============================================================", flush=True)
    test_curl_sistem()
    test_requests_cu_retry()
