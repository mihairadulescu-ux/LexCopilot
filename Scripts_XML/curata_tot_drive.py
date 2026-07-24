import os
import sys
import json
from pathlib import Path

# Stream live unbuffered
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))

# Bypass pentru verificarea din drive_config.py
if not os.getenv("DRIVE_FOLDER_XML"):
    os.environ["DRIVE_FOLDER_XML"] = "dummy_id"

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Importăm lista reală a celor 7 discuri
try:
    from drive_config import FOLDERE_XML_IDS
except ImportError:
    print("❌ Nu s-a putut importa FOLDERE_XML_IDS din drive_config.py!", flush=True)
    sys.exit(1)


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
            print(f"❌ [AUTH] Eroare parsare Service Account JSON: {e}", flush=True)
            sys.exit(1)
            
    print("❌ [AUTH] Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def curata_toate_discurile_reale():
    service = get_drive_service()

    # Curățăm doar ID-urile valide (ignorăm "dummy_id")
    ids_reale = [fid for fid in FOLDERE_XML_IDS if fid and fid != "dummy_id"]

    if not ids_reale:
        print("🛑 [EROARE CRITICĂ] Nu am găsit niciun ID real în FOLDERE_XML_IDS!", flush=True)
        sys.exit(1)

    print("============================================================", flush=True)
    print(f"⚠️ PORNIRE CURĂȚENIE TOTALĂ PE {len(ids_reale)} SHARED DRIVE-URI REALE", flush=True)
    print("============================================================", flush=True)

    total_sterse = 0

    for idx, folder_id in enumerate(ids_reale, start=1):
        print(f"\n📂 Curățare Shared Drive #{idx} (ID: {folder_id})...", flush=True)
        sterse_drive = 0
        page_token = None

        while True:
            try:
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    spaces='drive',
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=1000,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = response.get('files', [])
                if not files:
                    print(f"   ✨ Folderul/Drive-ul este gol.", flush=True)
                    break

                for f in files:
                    try:
                        service.files().delete(
                            fileId=f['id'],
                            supportsAllDrives=True,
                            supportsTeamDrives=True
                        ).execute()
                        sterse_drive += 1
                        total_sterse += 1

                        if sterse_drive % 200 == 0:
                            print(f"   🗑️ Șterse pe Drive #{idx}: {sterse_drive:,} fișiere...", flush=True)

                    except Exception as e_del:
                        print(f"   ⚠️ Eroare la ștergerea fișierului {f['name']}: {e_del}", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            except Exception as e:
                print(f"❌ Eroare la scanarea Drive #{idx}: {e}", flush=True)
                break

        print(f"✅ Drive #{idx} curățat complet! Total fișiere șterse: {sterse_drive:,}", flush=True)

    print("\n============================================================", flush=True)
    print(f"🏁 CURĂȚENIE TOTALĂ REUȘITĂ! Total fișiere eliminate: {total_sterse:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    curata_toate_discurile_reale()
