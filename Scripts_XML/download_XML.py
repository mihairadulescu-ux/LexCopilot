import sys
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
# CONFIGURĂRI DINAMICE ȘI CONSTANTE (JUST.RO)
# ==========================================
MAX_RETRIES_PER_PAGE = 4      # Încercări rapide per ciclu (3s, 6s, 12s, 24s)
MAX_FAILED_CYCLES = 3          # Câte cicluri de eșec permitem înainte să SĂRTIM pagina
PAUSE_BETWEEN_RETRIES = 3      # Pauza de start (secunde)
LOG_ERRORS_FILE = "pagini_saltate_erori.json"

# ENDPOINT-UL OFICIAL SI SCHEMA WSDL
SOAP_ENDPOINT_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc"
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

SOAP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Content-Type': 'text/xml; charset=utf-8',
    'SOAPAction': 'http://tempuri.org/IFreeWebService/GetLegislațieByAnPagina' # Numele acțiunii WCF
}


# ==========================================
# TEMPLATE PLIC SOAP (WCF ENVELOPE)
# ==========================================
def construieste_plic_soap(an, pagina):
    """
    Construiește corpul XML SOAP pentru serviciul WCF FreeWebService.svc.
    """
    soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:temp="http://tempuri.org/">
   <soapenv:Header/>
   <soapenv:Body>
      <temp:GetLegislațieByAnPagina>
         <temp:an>{an}</temp:an>
         <temp:pagina>{pagina}</temp:pagina>
      </temp:GetLegislațieByAnPagina>
   </soapenv:Body>
</soapenv:Envelope>"""
    return soap_body


# ==========================================
# FUNCȚII AUXILIARE DE LOGARE ȘI DEBUG
# ==========================================
def logheaza_pagina_saltata(an, pagina, url, motiv_detaliat):
    """Salvează incremental paginile care au eșuat definitiv într-un fișier JSON."""
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


def trimite_cerere_soap_cu_debug(url, xml_payload, timeout=30):
    """
    Execută cererea HTTP POST cu plic SOAP via curl_cffi pe serviciul WCF.
    """
    try:
        response = requests.post(
            url, 
            data=xml_payload.encode('utf-8'),
            headers=SOAP_HEADERS, 
            impersonate="chrome120", 
            http_version=CurlHttpVersion.V1_1,
            timeout=timeout
        )
        
        # 1. Răspuns Successful (200 OK)
        if response.status_code == 200:
            return True, response.content, "OK"
        
        # 2. Cod HTTP de eroare sau SOAP Fault
        motiv = f"HTTP {response.status_code} ({response.reason})"
        print(f"\n   ⚠️ [HTTP STATUS ERROR] Cod {response.status_code} ({response.reason}) pe URL: {url}", flush=True)
        if response.text:
            print(f"      📄 Preview Răspuns SOAP (200 chars): {response.text[:200]!r}", flush=True)
        return False, None, motiv

    except requests.errors.RequestsError as e:
        motiv = f"curl_cffi Error ({type(e).__name__}): {e}"
        print(f"\n   ❌ [cURL Error Exact]: {type(e).__name__} -> {e}", flush=True)
        return False, None, motiv

    except Exception as e:
        motiv = f"Eroare Necunoscută ({type(e).__name__}): {e}"
        print(f"\n   💥 [Eroare Generală]: {type(e).__name__} -> {e}", flush=True)
        return False, None, motiv


# ==========================================
# BUCLA PRINCIPALĂ DE DESCĂRCARE PER AN/PAGINĂ
# ==========================================
def proceseaza_descarcare_an(an, pagina_start=1):
    """Procesează descărcarea paginilor pentru un an specific, cu tratare de erori și Skip."""
    print(f"\n=== AN INDUSTRIAL XML (SOAP WCF): {an} ===", flush=True)
    print(f"🆕 An {an}: Începem de la pagina {pagina_start}.", flush=True)
    
    pagina_curenta = pagina_start
    cicluri_esuate_consecutive = 0
    
    while True:
        xml_payload = construieste_plic_soap(an, pagina_curenta)
        
        print(f"--- [AVANS SOAP] An {an} / Pagina {pagina_curenta} ---", flush=True)
        
        succes = False
        ultimul_motiv_esec = ""
        
        for incercare in range(1, MAX_RETRIES_PER_PAGE + 1):
            pauza = PAUSE_BETWEEN_RETRIES * (2 ** (incercare - 1))  # Backoff: 3s, 6s, 12s, 24s
            
            ok, continut_xml_raspuns, motiv = trimite_cerere_soap_cu_debug(SOAP_ENDPOINT_URL, xml_payload)
            
            if ok:
                succes = True
                cicluri_esuate_consecutive = 0
                
                # Aici salvezi conținutul XML returnat (în fișier sau pe Google Drive)
                
                break
            else:
                ultimul_motiv_esec = motiv
                print(f"   ⚠️ Încercarea {incercare}/{MAX_RETRIES_PER_PAGE} eșuată pe pagina {pagina_curenta}. Pauză {pauza}s...", flush=True)
                time.sleep(pauza)
        
        if succes:
            pagina_curenta += 1
        else:
            cicluri_esuate_consecutive += 1
            print(f"\n🛑 [Pagină Eșuată] Pagina {pagina_curenta} a eșuat în ciclul {cicluri_esuate_consecutive}/{MAX_FAILED_CYCLES}.", flush=True)
            
            if cicluri_esuate_consecutive >= MAX_FAILED_CYCLES:
                print(f"⚠️ [SKIP PAGINĂ] Pagina {pagina_curenta} eșuează sistematic! O salvăm în log și SĂRTIM la pagina {pagina_curenta + 1}...", flush=True)
                
                logheaza_pagina_saltata(
                    an=an, 
                    pagina=pagina_curenta, 
                    url=SOAP_ENDPOINT_URL, 
                    motiv_detaliat=ultimul_motiv_esec
                )
                
                pagina_curenta += 1
                cicluri_esuate_consecutive = 0
            else:
                print("   ⏸️ Așteptăm 30 de secunde înainte de a reîncerca aceeași pagină...", flush=True)
                time.sleep(30)


# ==========================================
# MAIN ENTRYPOINT
# ==========================================
def main():
    print("🚀 Script de descărcare SOAP XML pornit (FreeWebService.svc via curl_cffi).", flush=True)
    
    ani_de_procesat = [2012, 2013]
    if len(sys.argv) >= 3:
        try:
            an_start = int(sys.argv[1])
            an_stop = int(sys.argv[2])
            ani_de_procesat = list(range(an_start, an_stop + 1))
        except ValueError:
            print("⚠️ Argumentele din linia de comandă nu sunt numere valide. Folosim valorile default.", flush=True)

    for an in ani_de_procesat:
        proceseaza_descarcare_an(an, pagina_start=2480 if an == 2012 else 1)

    print("\n✅ Descărcare încheiată cu succes pentru toți anii specificați!", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Procesul a fost întrerupt manual de utilizator (Ctrl+C). Exiting cleanly...", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 [CRITICAL SCRIPT ERROR] A apărut o eroare fatală neprinsă:", flush=True)
        print(f"   Tip Eroare: {type(e).__name__}", flush=True)
        print(f"   Mesaj: {e}", flush=True)
        print("\n📜 Traceback complet:", flush=True)
        traceback.print_exc()
        
        sys.exit(0)
