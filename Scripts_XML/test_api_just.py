# Filename: Scripts_XML/test_api_just.py
# Scop: Test manual rapid pentru verificarea stării reale a API-ului SOAP Just.ro.
# Usage: python Scripts_XML/test_api_just.py [AN_TEST] [PAGINA_TEST]

import os
import sys
import time
import requests
from suds.client import Client

# Stream live pentru consolă
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

WSDL_URL = os.getenv("JUST_RO_WSDL_URL") or "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"
ENDPOINT_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc"

# Culori pentru consolă
VERDE = "\033[92m"
ROSU = "\033[91m"
GALBEN = "\033[93m"
ALBASTRU = "\033[94m"
RESET = "\033[0m"


def testeaza_api(an_test=1990, pagina_test=1):
    print("=" * 65)
    print(f"{ALBASTRU}🔍 TEST DIAGNOSTIC API LEGISLATE.JUST.RO{RESET}")
    print("=" * 65)
    print(f"📡 WSDL Endpoint: {WSDL_URL}")
    print(f"🎯 Parametri test: An = {an_test} | Pagina = {pagina_test}\n")

    # Step 1: Preluare Token SOAP
    print("1️⃣ [STEP 1] Solicitare Token nou SOAP...", end=" ", flush=True)
    start_token = time.time()
    try:
        client = Client(WSDL_URL, timeout=15)
        token = client.service.GetToken()
        durata_token = time.time() - start_token

        if token and len(token) > 10:
            print(f"{VERDE}OK!{RESET} (obținut în {durata_token:.2f}s)")
            print(f"   🔑 Token primit: {token[:15]}...{token[-5:]}")
        else:
            print(f"{ROSU}ESEC!{RESET} Token-ul returnat este gol sau invalid.")
            sys.exit(1)
    except Exception as e:
        print(f"{ROSU}EROARE!{RESET}")
        print(f"   ❌ Nu s-a putut conecta la WSDL: {e}")
        sys.exit(1)

    print()

    # Step 2: Apel Search SOAP
    print(f"2️⃣ [STEP 2] Trimitere cerere Search XML (An {an_test}, Pag {pagina_test})...", end=" ", flush=True)
    soap_request = f"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:ns0="http://schemas.datacontract.org/2004/07/FreeWebService" xmlns:ns1="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns2="http://tempuri.org/">
   <SOAP-ENV:Header/>
   <ns1:Body>
      <ns2:Search>
         <ns2:SearchModel>
            <ns0:NumarPagina>{pagina_test}</ns0:NumarPagina>
            <ns0:RezultatePagina>10</ns0:RezultatePagina>
            <ns0:SearchAn>{an_test}</ns0:SearchAn>
         </ns2:SearchModel>
         <ns2:tokenKey>{token}</ns2:tokenKey>
      </ns2:Search>
   </ns1:Body>
</SOAP-ENV:Envelope>"""

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/Search"
    }

    start_search = time.time()
    try:
        resp = requests.post(ENDPOINT_URL, data=soap_request, headers=headers, timeout=25)
        durata_search = time.time() - start_search
        
        continut_raw = resp.text.strip()
        dimensiune_bytes = len(resp.content)

        print(f"Status HTTP: {resp.status_code} (răspuns în {durata_search:.2f}s)")
        print("-" * 65)

        # Step 3: Analiză Răspuns
        if resp.status_code == 200:
            if dimensiune_bytes == 0:
                print(f"{ROSU}❌ PROBLEMA DETECTATĂ (0 BYTES)!{RESET}")
                print("   Serverul a întors Status 200 OK, dar corpul răspunsului are ZERO BĂIȚI.")
                print("   👉 Diagnostic: API-ul de la Minister sughite sau are backend-ul de date oprit.")
            elif "<" not in continut_raw or "Envelope>" not in continut_raw:
                print(f"{GALBEN}⚠️ RĂSPUNS INVALID / CORUPT!{RESET}")
                print(f"   Dimensiune primit: {dimensiune_bytes} bytes.")
                print(f"   Fragment primit: {continut_raw[:150]}")
            else:
                print(f"{VERDE}🟢 API-UL FUNCTIONEAZA IN PARAMETRI OPTIMI!{RESET}")
                print(f"   📦 Dimensiune pachet XML valid: {dimensiune_bytes:,} bytes")
                print("   ✅ Răspunsul conține plic SOAP structurat corect.")
        else:
            print(f"{ROSU}❌ EROARE HTTP {resp.status_code}!{RESET}")
            print(f"   Sursa: {continut_raw[:200]}")

    except Exception as e:
        print(f"{ROSU}EROARE RETEA / TIMEOUT!{RESET}")
        print(f"   ❌ {e}")

    print("=" * 65 + "\n")


if __name__ == "__main__":
    an = int(sys.argv[1]) if len(sys.argv) > 1 else 1990
    pag = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    testeaza_api(an, pag)
