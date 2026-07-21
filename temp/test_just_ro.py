import os
import sys
import time
import json
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

# Instalare/Import automat suds pentru comunicare SOAP WSDL
try:
    from suds.client import Client
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "suds-py3"], check=True)
    from suds.client import Client


AN_TEST = 1990
PAGINA_TEST = 1
REZULTATE_PER_PAGINA = 10

URL_WSDL_OFFICIAL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"


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
        file_id = res_file.get("id")
        print(f"💾 Salvat cu succes în Folderul de Indecși Google Drive: {nume_fisier_drive} (ID: {file_id})", flush=True)
        return file_id
    except Exception as e:
        print(f"❌ Eroare la încărcarea în Google Drive: {e}", flush=True)
        return None


# ==============================================================================
# EXECUȚIE TEST SOAP WSDL OFICIAL
# ==============================================================================
def test_soap_wsdl_official(service):
    print(f"\n🌐 Conectare la Serviciul WSDL Oficial: {URL_WSDL_OFFICIAL}...", flush=True)

    try:
        # Initializare client SOAP pe adresa apiws
        client = Client(URL_WSDL_OFFICIAL)
        
        print("🔑 Solicitare Token de acces prin GetToken()...", flush=True)
        token = client.service.GetToken()
        print(f"✅ TOKEN OBȚINUT: {token}", flush=True)

        print(f"⚙️ Configurare SearchModel pentru An={AN_TEST}, Pagina={PAGINA_TEST}...", flush=True)
        search_model = client.factory.create('SearchModel')
        search_model.NumarPagina = PAGINA_TEST
        search_model.RezultatePagina = REZULTATE_PER_PAGINA
        search_model.SearchAn = AN_TEST

        print("📡 Trimitere cerere SOAP Search()...", flush=True)
        raspuns_soap = client.service.Search(search_model, token)

        # Convertim răspunsul în text XML/JSON brut pentru salvare
        text_raw = str(raspuns_soap)

        print("\n" + "=" * 50, flush=True)
        print("📄 PRIMELE 500 CARACTERE DIN REZULTATUL PRIMIT:", flush=True)
        print("=" * 50, flush=True)
        print(text_raw[:500], flush=True)
        print("=" * 50 + "\n", flush=True)

        if text_raw.strip():
            nume_local = f"TEST_SOAP_OFFICIAL_{AN_TEST}_pag{PAGINA_TEST}.xml"
            nume_drive = f"TEST_SOAP_OFFICIAL_brut_legislatie_{AN_TEST}_pag{PAGINA_TEST}.xml"

            with open(nume_local, "w", encoding="utf-8") as f:
                f.write(text_raw)

            incarca_fisier_in_drive(service, nume_local, nume_drive)

            if os.path.exists(nume_local):
                os.remove(nume_local)

    except Exception as e:
        print(f"❌ Excepție la interogarea WSDL Oficială: {e}", flush=True)


def main():
    print("============================================================", flush=True)
    print("🚀 TEST INTEROGARE WSDL OFICIAL (apiws/FreeWebService.svc)", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()
    test_soap_wsdl_official(service)

    print("============================================================", flush=True)
    print("🏁 TEST FINALIZAT!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
