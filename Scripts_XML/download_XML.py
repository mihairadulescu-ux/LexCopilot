vimport sys
import os
import time
import json
import traceback
import subprocess

# Auto-instalare dinamică și import pentru curl_cffi + CurlHttpVersion
try:
    from curl_cffi import requests, CurlHttpVersion
except ImportError:
    print("📦 Pachetul 'curl_cffi' nu a fost găsit. Se instalează automat...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "curl_cffi"])
    try:
        from curl_cffi import requests, CurlHttpVersion
    except ImportError:
        from curl_cffi import requests
        from curl_cffi.const import CurlHttpVersion
    print("✅ 'curl_cffi' a fost instalat cu succes!", flush=True)


# ==========================================
# CONFIGURĂRI SI ENDPOINT OFICIAL
# ==========================================
MAX_RETRIES_PER_PAGE = 4
MAX_FAILED_CYCLES = 3
PAUSE_BETWEEN_RETRIES = 3
LOG_ERRORS_FILE = "pagini_saltate_erori.json"

SOAP_ENDPOINT_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc"

HEADERS_BASE = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Content-Type': 'text/xml; charset=utf-8'
}


# ==========================================
# FUNCȚII GENERARE PLICURI SOAP
# ==========================================
def construieste_plic_get_token():
    return """<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Header>
    <Action s:mustUnderstand="1" xmlns="http://schemas.microsoft.com/ws/2005/05/addressing/none">http://tempuri.org/IFreeWebService/GetToken</Action>
  </s:Header>
  <s:Body>
    <GetToken xmlns="http://tempuri.org/" />
  </s:Body>
</s:Envelope>"""


def construieste_plic_search(token_key, an, pagina, rezultate_per_pagina=10):
    return f"""<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Header>
    <Action s:mustUnderstand="1" xmlns="http://schemas.microsoft.com/ws/2005/05/addressing/none">http://tempuri.org/IFreeWebService/Search</Action>
  </s:Header>
  <s:Body>
    <Search xmlns="http://tempuri.org/">
      <SearchModel xmlns:d4p1="http://schemas.datacontract.org/2004/07/FreeWebService" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
        <d4p1:NumarPagina>{pagina}</d4p1:NumarPagina>
        <d4p1:RezultatePagina>{rezultate_per_pagina}</d4p1:RezultatePagina>
        <d4p1:SearchAn>{an}</d4p1:SearchAn>
        <d4p1:SearchNumar i:nil="true" />
        <d4p1:SearchText i:nil="true" />
        <d4p1:SearchTitlu i:nil="true" />
      </SearchModel>
      <tokenKey>{token_key}</tokenKey>
    </Search>
  </s:Body>
</s:Envelope>"""


# ==========================================
# LOGICĂ REȚEA ȘI MANAGEMENT TOKEN
# ==========================================
def obtine_token():
    """Apelează GetToken doar când este necesar un token nou."""
    print("🔑 [TOKEN] Solicităm un token nou de la serviciul web...", flush=True)
    payload = construieste_plic_get_token()
    
    headers = HEADERS_BASE.copy()
    headers['SOAPAction'] = 'http://tempuri.org/IFreeWebService/GetToken'
    
    try:
        response = requests.post(
            SOAP_ENDPOINT_URL,
            data=payload.encode('utf-8'),
            headers=headers,
            impersonate="chrome120",
            http_version=CurlHttpVersion.V1_1,
            timeout=20
        )
        
        if response.status_code == 200:
            text = response.text
            if "<GetTokenResult>" in text and "</GetTokenResult>" in text:
                token = text.split("<GetTokenResult>")[1].split("</GetTokenResult>")[0].strip()
                print(f"✅ [TOKEN OK] Token activat: {token[:15]}...", flush=True)
                return token
        
        print(f"❌ [TOKEN ERROR] Cod HTTP {response.status_code}: {response.text[:200]}", flush=True)
        return None
    except Exception as e:
        print(f"💥 [TOKEN EXCEPTION] {type(e).__name__}: {e}", flush=True)
        return None


def trimite_search_soap(token_key, an, pagina, timeout=30):
    payload = construieste_plic_search(token_key, an, pagina)
    headers = HEADERS_BASE.copy()
    headers['SOAPAction'] = 'http://tempuri.org/IFreeWebService/Search'
    
    try:
        response = requests.post(
            SOAP_ENDPOINT_URL,
            data=payload.encode('utf-8'),
            headers=headers,
            impersonate="chrome120",
            http_version=CurlHttpVersion.V1_1,
            timeout=timeout
        )
        
        if response.status_code == 200:
            # Verificăm dacă răspunsul conține erori specifice de token nevalid/expirat
            if "Invalid Token" in response.text or "Token Expired" in response.text:
                return False, None, "TOKEN_EXPIRED"
            return True, response.content, "OK"
        
        if response.status_code in (401, 403):
            return False, None, "TOKEN_EXPIRED"

        motiv = f"HTTP {response.status_code} ({response.reason})"
        print(f"\n   ⚠️ [HTTP STATUS ERROR] Cod {response.status_code} pe URL: {SOAP_ENDPOINT_URL}", flush=True)
        return False, None, motiv

    except requests.errors.RequestsError as e:
        motiv = f"curl_cffi Error ({type(e).__name__}): {e}"
        print(f"\n   ❌ [cURL Error Exact]: {type(e).__name__} -> {e}", flush=True)
        return False, None, motiv
    except Exception as e:
        motiv = f"Eroare Necunoscută ({type(e).__name__}): {e}"
        print(f"\n   💥 [Eroare Generală]: {type(e).__name__} -> {e}", flush=True)
        return False, None, motiv


def logheaza_pagina_saltata(an, pagina, url, motiv_detaliat):
    entry = {
        "an": an,
        "pagina": pagina,
        "url": url,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "motiv": str(motiv_detaliat)
    }
    
    date_existente = []
    if os.path.exists(LOG_ERRORS_FILE):
        try:
            with open(LOG_ERRORS_FILE, "r", encoding="utf-8") as f:
                date_existente = json.load(f)
        except Exception:
            date_existente = []

    date_existente.append(entry)
    
    try:
        with open(LOG_ERRORS_FILE, "w", encoding="utf-8") as f:
            json.dump(date_existente, f, ensure_ascii=False, indent=2)
        print(f"   📝 [LOGGED] Pagina {pagina} din anul {an} a fost salvată în '{LOG_ERRORS_FILE}'.", flush=True)
    except Exception as e:
        print(f"   ⚠️ Nu s-a putut scrie în fișierul de log: {e}", flush=True)


# ==========================================
# BUCLA PRINCIPALĂ PER AN/PAGINĂ
# ==========================================
def proceseaza_descarcare_an(an, pagina_start=1, token_salvat=None):
    print(f"\n=== AN INDUSTRIAL XML (SOAP OFICIAL): {an} ===", flush=True)
    
    # Folosim token-ul existent sau obținem unul nou doar dacă nu există
    token_curent = token_salvat or obtine_token()
    if not token_curent:
        print("❌ Nu s-a putut obține token-ul inițial. Abandonăm anul curent.", flush=True)
        return None

    pagina_curenta = pagina_start
    cicluri_esuate_consecutive = 0
    
    while True:
        print(f"--- [AVANS SEARCH] An {an} / Pagina {pagina_curenta} ---", flush=True)
        
        succes = False
        ultimul_motiv_esec = ""
        
        for incercare in range(1, MAX_RETRIES_PER_PAGE + 1):
            pauza = PAUSE_BETWEEN_RETRIES * (2 ** (incercare - 1))
            
            ok, continut_xml, motiv = trimite_search_soap(token_curent, an, pagina_curenta)
            
            if ok:
                succes = True
                cicluri_esuate_consecutive = 0
                # Aici salvezi conținutul XML
                break
            else:
                ultimul_motiv_esec = motiv
                # Re-generare token DOAR dacă serverul indică explicit că primul a expirat
                if motiv == "TOKEN_EXPIRED":
                    print("🔄 [TOKEN EXPIRED] Tokenul curent a expirat. Obținem un token nou...", flush=True)
                    token_nou = obtine_token()
                    if token_nou:
                        token_curent = token_nou

                print(f"   ⚠️ Încercarea {incercare}/{MAX_RETRIES_PER_PAGE} eșuată pe pagina {pagina_curenta}. Pauză {pauza}s...", flush=True)
                time.sleep(pauza)
        
        if succes:
            pagina_curenta += 1
        else:
            cicluri_esuate_consecutive += 1
            print(f"\n🛑 [Pagină Eșuată] Pagina {pagina_curenta} a eșuat în ciclul {cicluri_esuate_consecutive}/{MAX_FAILED_CYCLES}.", flush=True)
            
            if cicluri_esuate_consecutive >= MAX_FAILED_CYCLES:
                print(f"⚠️ [SKIP PAGINĂ] Pagina {pagina_curenta} eșuează sistematic! O salvăm în log și SĂRTIM...", flush=True)
                logheaza_pagina_saltata(an, pagina_curenta, SOAP_ENDPOINT_URL, ultimul_motiv_esec)
                pagina_curenta += 1
                cicluri_esuate_consecutive = 0
            else:
                print("   ⏸️ Așteptăm 30 de secunde înainte de a reîncerca...", flush=True)
                time.sleep(30)
                
    return token_curent


def main():
    print("🚀 Script de descărcare conform documentației oficiale legislatie.just.ro", flush=True)
    
    ani_de_procesat = [2012, 2013]
    if len(sys.argv) >= 3:
        try:
            an_start = int(sys.argv[1])
            an_stop = int(sys.argv[2])
            ani_de_procesat = list(range(an_start, an_stop + 1))
        except ValueError:
            print("⚠️ Argumentele din linia de comandă nu sunt valide. Folosim valorile default.", flush=True)

    token_activ = None
    for an in ani_de_procesat:
        token_activ = proceseaza_descarcare_an(
            an, 
            pagina_start=2480 if an == 2012 else 1, 
            token_salvat=token_activ
        )

    print("\n✅ Descărcare încheiată cu succes!", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Proces întrerupt manual de utilizator.", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 [CRITICAL ERROR]: {e}", flush=True)
        traceback.print_exc()
        sys.exit(0)
