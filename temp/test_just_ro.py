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

# Endpoint-ul OFICIAL pe HTTP
URL_GET_LEGI_HTTP = "http://legislatie.just.ro/api/Search/GetLegi"

AN_TEST = 1990
PAGINA_TEST = 1
REZULTATE_PER_PAGINA = 10


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
        file_id = res_file.get("id")
        print(f"💾 Salvat cu succes în Folderul de Indecși Google Drive: {nume_fisier_drive} (ID: {file_id})", flush=True)
        return file_id
    except Exception as e:
        print(f"❌ Eroare la încărcarea în Google Drive: {e}", flush=True)
        return None


# ==============================================================================
# EXECUȚIE TEST PE GETLEGI
# ==============================================================================
def test_get_legi_http(service):
    print(f"\n🔍 Interogare HTTP oficială pe: {URL_GET_LEGI_HTTP}...", flush=True)

    session = requests.Session()

    # Antete HTTP complete pentru a evita respingerea de către IIS/ASP.NET
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json; charset=utf-8",
        "Origin": "http://legislatie.just.ro",
        "Referer": "http://legislatie.just.ro/",
        "Connection": "keep-alive"
    }

    # Structura clasică de căutare pe an și pagină
    payload = {
        "SearchAn": str(AN_TEST),
        "NumarPagina": PAGINA_TEST,
        "RezultatePagina": REZULTATE_PER_PAGINA
    }

    try:
        # 1. Trecem mai întâi prin pagina de bază HTTP pentru inițializarea cookie-urilor de sesiune
        print("🌐 Inițializare sesiune HTTP pe http://legislatie.just.ro/...", flush=True)
        session.get("http://legislatie.just.ro/", headers={"User-Agent": headers["User-Agent"]}, timeout=10)
        time.sleep(1)

        # 2. Trimitem cererea POST de căutare
        print(f"📡 Trimitem POST la GetLegi (An: {AN_TEST}, Pagina: {PAGINA_TEST})...", flush=True)
        response = session.post(URL_GET_LEGI_HTTP, json=payload, headers=headers, timeout=20)

        print(f"📡 Status Code HTTP: {response.status_code}", flush=True)
        print(f"📊 Dimensiune răspuns: {len(response.content):,} octeți", flush=True)

        text_raw = response.text or ""

        print("\n" + "=" * 50, flush=True)
        print("📄 PRIMELE 500 CARACTERE DIN RĂSPUNSUL PRIMIT:", flush=True)
        print("=" * 50, flush=True)
        print(text_raw[:500], flush=True)
        print("=" * 50 + "\n", flush=True)

        if text_raw.strip():
            nume_local = f"TEST_GETLEGI_{AN_TEST}_pag{PAGINA_TEST}.xml"
            nume_drive = f"TEST_GETLEGI_brut_legislatie_{AN_TEST}_pag{PAGINA_TEST}.xml"

            with open(nume_local, "w", encoding="utf-8") as f:
                f.write(text_raw)

            incarca_fisier_in_drive(service, nume_local, nume_drive)

            if os.path.exists(nume_local):
                os.remove(nume_local)

    except Exception as e:
        print(f"❌ Excepție la interogarea GetLegi: {e}", flush=True)


def main():
    print("============================================================", flush=True)
    print("🚀 TEST INTEROGARE DIRECTĂ GETLEGI (HTTP PORT 80)", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()
    test_get_legi_http(service)

    print("============================================================", flush=True)
    print("🏁 TEST FINALIZAT!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
