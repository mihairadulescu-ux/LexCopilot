import os
import sys
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

AN_TEST = 1990
PAGINA_TEST = 1
REZULTATE_PER_PAGINA = 10

# URL-urile WSDL specifice Just.ro
URL_URI_WSDL = [
    "http://legislatie.just.ro/api/CautareService.svc?wsdl",
    "http://legislatie.just.ro/Services/CautareService.svc?wsdl",
    "http://legislatie.just.ro/api/CautareService.svc",
]


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API
# ==============================================================================
def get_drive_service():
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
            print(f"❌ Eroare secret JSON: {e}", flush=True)
            sys.exit(1)

    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare citire service_account.json: {e}", flush=True)

    print("❌ Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def incarca_fisier_in_drive(service, cale_locala, nume_fisier_drive):
    try:
        media = MediaFileUpload(cale_locala, mimetype="text/xml")
        file_metadata = {
            "name": nume_fisier_drive,
            "parents": [FOLDER_TEMP_INDEXES_ID]
        }
        params = get_file_params()
        params["body"] = file_metadata
        params["media_body"] = media
        res_file = service.files().create(**params).execute()
        print(f"💾 Salvat cu succes în Google Drive: {nume_fisier_drive} (ID: {res_file.get('id')})", flush=True)
    except Exception as e:
        print(f"❌ Eroare încărcare Drive: {e}", flush=True)


# ==============================================================================
# INTEROGARE WSDL / SOAP
# ==============================================================================
def test_wsdl_endpoint(service, url_wsdl):
    print(f"\n🔍 Încercare interogare WSDL pe: {url_wsdl}...", flush=True)

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ICautareService/GetLegi",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    # Plicul SOAP standard pentru serviciul de căutare Just.ro
    soap_payload = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:temp="http://tempuri.org/">
   <soapenv:Header/>
   <soapenv:Body>
      <temp:GetLegi>
         <temp:searchAn>{AN_TEST}</temp:searchAn>
         <temp:numarPagina>{PAGINA_TEST}</temp:numarPagina>
         <temp:rezultatePagina>{REZULTATE_PER_PAGINA}</temp:rezultatePagina>
      </temp:GetLegi>
   </soapenv:Body>
</soapenv:Envelope>"""

    try:
        response = requests.post(url_wsdl, data=soap_payload, headers=headers, timeout=20)
        print(f"📡 Status HTTP: {response.status_code}", flush=True)
        print(f"📊 Dimensiune răspuns: {len(response.content):,} octeți", flush=True)
        
        text_raw = response.text or ""

        print("\n" + "=" * 50, flush=True)
        print("📄 PRIMELE 500 CARACTERE DIN RĂSPUNSUL SOAP/WSDL:", flush=True)
        print("=" * 50, flush=True)
        print(text_raw[:500], flush=True)
        print("=" * 50 + "\n", flush=True)

        if response.status_code == 200 and text_raw.strip():
            nume_local = f"TEST_WSDL_{AN_TEST}_pag{PAGINA_TEST}.xml"
            nume_drive = f"TEST_WSDL_brut_legislatie_{AN_TEST}_pag{PAGINA_TEST}.xml"

            with open(nume_local, "w", encoding="utf-8") as f:
                f.write(text_raw)

            incarca_fisier_in_drive(service, nume_local, nume_drive)

            if os.path.exists(nume_local):
                os.remove(nume_local)
            return True

    except Exception as e:
        print(f"❌ Excepție la interogare WSDL pe {url_wsdl}: {e}", flush=True)
        return False


def main():
    print("============================================================", flush=True)
    print("🚀 TEST INTEROGARE WSDL / SOAP JUST.RO", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()

    for url_wsdl in URL_URI_WSDL:
        succes = test_wsdl_endpoint(service, url_wsdl)
        if succes:
            break

    print("============================================================", flush=True)
    print("🏁 TEST FINALIZAT!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
