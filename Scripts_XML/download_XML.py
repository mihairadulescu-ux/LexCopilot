import sys
import time
import traceback
import requests
import http.client

def descatca_pagina_cu_debug(url, session=None, timeout=30):
    """
    Execută request-ul și printează detalii complete despre
    orice eroare HTTP sau de Rețea/Socket întâlnită.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Connection': 'close' # Evită refolosirea socket-urilor moarte
    }
    
    requester = session if session else requests
    
    try:
        response = requester.get(url, headers=headers, timeout=timeout)
        
        # Dacă răspunsul este OK (200)
        if response.status_code == 200:
            return response.content
        
        # Dacă serverul a trimis un cod HTTP de eroare (ex: 500, 502, 503, 504, 429)
        print(f"\n⚠️ [HTTP STATUS ERROR] {response.status_code} {response.reason} pe URL: {url}")
        print(f"   📄 Primele 200 caractere răspuns: {response.text[:200]!r}")
        return None

    except requests.exceptions.HTTPError as e:
        print(f"\n❌ [HTTPError Exact]: Status Code: {e.response.status_code} | Mesaj: {e}")
        
    except requests.exceptions.ConnectionError as e:
        # Prinde cazurile de RemoteDisconnected, ConnectionResetError, DNS, etc.
        print(f"\n❌ [ConnectionError Exact]: {type(e).__name__}")
        print(f"   💬 Detaliu Excepție: {e}")
        
        # Extrage motivul intern dacă există (ex: RemoteDisconnected)
        if hasattr(e, 'args') and e.args:
            print(f"   🔍 Cause / Sub-Eroare: {e.args[0]}")

    except requests.exceptions.Timeout as e:
        print(f"\n⏳ [Timeout Error]: Serverul nu a răspuns în {timeout} secunde. ({e})")

    except Exception as e:
        # Orice altă eroare neașteptată
        print(f"\n💥 [Eroare Necunoscută]: {type(e).__name__} -> {e}")
        print(f"   📜 Traceback: {traceback.format_exc().replace(chr(10), ' | ')}")
        
    return None
