import os
import sys
import time
import json
import requests
from pathlib import Path

# ==============================================================================
# CONFIGURARE CĂI DE IMPORT
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from drive_config import (
    FOLDER_TEMP_INDEXES_ID,
    get_file_params,
)

# ==============================================================================
# CONFIGURARE TEST LEGISLATE.JUST.RO
# ==============================================================================
AN_TEST = 1990
PAGINA_TEST = 1
REZULTATE_PER_PAGINA = 10

URL_JUST_API = "https://legislatie.just.ro/api/Search/GetLegi"
URL_SOAP_WSDL = "https://legislatie.just.ro/api/CautareService.svc"


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API
# ==============================================================================
def get_drive_service():
    """Autentificare în Google Drive API folosind GOOGLE_SERVICE_ACCOUNT_JSON."""
    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )

    if creds_json:
        try:
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare la citirea secretului JSON: {e}", flush=True)
            sys.exit(1)

    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare la citirea fișierului local service_account.json: {e}", flush=True)

    print("❌ Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def incarca_fisier_in_drive(service, cale_locala, nume_fisier_drive, mime_type="text/xml"):
    """Încarcă fișierul direct în folderul de indecși din Google Drive."""
    try:
        media = MediaFileUpload(cale_locala, mimetype=mime_type)
        file_metadata = {
            "name": nume_fisier_drive,
            "parents": [FOLDER_TEMP_INDEXES_ID]
        }
        
        params = get_file_params()
        params["body"] = file_metadata
        params["media_body"] = media
        
        res_file = service.files().create(**params).execute()
        file_id = res_file.get("id")
        print(f"💾 Salvat cu succes în Folderul de Indecși Google Drive: {nume_fisier_drive} (ID: {file_id})", flush=True)
        return file_id
    except Exception as e:
        print(f"❌ Eroare la încărcarea în Google Drive: {e}", flush=True)
        return None


# ==============================================================================
# CREARE SESIUNE HTTP SIMULATĂ BROWSER
# ==============================================================================
def creeaza_sesiune_browser():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://legislatie.just.ro",
        "Referer": "https://legislatie.just.ro/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Connection": "keep-alive"
    })
    return session


# ==============================================================================
# METODA 1: INTEROGARE REST / JSON WRAPPER CU BROWSER HEADER
# ==============================================================================
def test_metoda_json_api(service, session, an, pagina):
    print(f"\n🔍 [TEST 1 - REST/JSON] Încercare interogare API Just.ro pentru An: {an}, Pagina: {pagina}...", flush=True)

    payload = {
        "SearchAn": str(an),
        "NumarPagina": pagina,
        "RezultatePagina": REZULTATE_PER_PAGINA
    }

    try:
        # Preluăm mai întâi cookie-ul de sesiune de pe pagina principală
        session.get("https://legislatie.just.ro/", timeout=15)
        time.sleep(1)

        response = session.post(URL_JUST_API, json=payload, timeout=20)
        print(f"📡 Status HTTP: {response.status_code}", flush=True)
        print(f"📊 Dimensiune răspuns: {len(response.content):,} octeți", flush=True)
        
        text_raw = response.text or ""
        print("\n--- PRIMELE 500 CARACTERE DIN RĂSPUNS JSON/REST ---", flush=True)
        print(text_raw[:500], flush=True)
        print("--------------------------------------------------\n", flush=True)

        if text_raw.strip():
            nume_fisier_local = f"TEST_JSON_{an}_pag{pagina}.xml"
            nume_drive = f"TEST_JSON_brut_legislatie_{an}_pag{pagina}.xml"

            with open(nume_fisier_local, "w", encoding="utf-8") as f:
                f.write(text_raw)

            incarca_fisier_in_drive(service, nume_fisier_local, nume_drive, "text/xml")

            if os.path.exists(nume_fisier_local):
                os.remove(nume_fisier_local)

    except Exception as e:
        print(f"❌ Excepție la interogare JSON: {e}", flush=True)


# ==============================================================================
# METODA 2: INTEROGARE DIRECTĂ SOAP ENVELOPE XML
# ==============================================================================
def test_metoda_soap_xml(service, session, an, pagina):
    print(f"\n🔍 [TEST 2 - SOAP XML] Încercare interogare SOAP WSDL pentru An: {an}, Pagina: {pagina}...", flush=True)

    soap_headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ICautareService/GetLegi"
    }

    soap_payload = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:temp="http://tempuri.org/">
   <soapenv:Header/>
   <soapenv:Body>
      <temp:GetLegi>
         <temp:searchAn>{an}</temp:searchAn>
         <temp:numarPagina>{pagina}</temp:numarPagina>
         <temp:rezultatePagina>{REZULTATE_PER_PAGINA}</temp:rezultatePagina>
      </temp:GetLegi>
   </soapenv:Body>
</soapenv:Envelope>"""

    try:
        response = session.post(URL_SOAP_WSDL, data=soap_payload, headers=soap_headers, timeout=20)
        print(f"📡 Status HTTP: {response.status_code}", flush=True)
        print(f"📊 Dimensiune răspuns: {len(response.content):,} octeți", flush=True)

        text_raw = response.text or ""
        print("\n--- PRIMELE 500 CARACTERE DIN RĂSPUNS SOAP ---", flush=True)
        print(text_raw[:500], flush=True)
        print("----------------------------------------------\n", flush=True)

        if text_raw.strip():
            nume_fisier_local = f"TEST_SOAP_{an}_pag{pagina}.xml"
            nume_drive = f"TEST_SOAP_brut_legislatie_{an}_pag{pagina}.xml"

            with open(nume_fisier_local, "w", encoding="utf-8") as f:
                f.write(text_raw)

            incarca_fisier_in_drive(service, nume_fisier_local, nume_drive, "text/xml")

            if os.path.exists(nume_fisier_local):
                os.remove(nume_fisier_local)

    except Exception as e:
        print(f"❌ Excepție la interogare SOAP: {e}", flush=True)


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
def main():
    print("============================================================", flush=True)
    print("🚀 PORNIRE TEST INTEROGARE JUST.RO (GITHUB ACTIONS execution)", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()
    session = creeaza_sesiune_browser()

    test_metoda_json_api(service, session, AN_TEST, PAGINA_TEST)
    test_metoda_soap_xml(service, session, AN_TEST, PAGINA_TEST)

    print("\n============================================================", flush=True)
    print("🏁 TEST FINALIZAT!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
