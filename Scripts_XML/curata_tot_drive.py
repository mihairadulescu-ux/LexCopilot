import os
import sys
import json
import time
from pathlib import Path

# Stream live unbuffered pentru GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Importăm direct lista celor 7 discuri
try:
    from drive_config import FOLDERE_XML_IDS
except ImportError:
    # Backup în caz că nu poate fi importat modulul drive_config
    FOLDERE_XML_IDS = [
        "1O9c1S2_48gG1IqX3hGzO8e0Z",  # Pune ID-urile tale aici dacă e cazul
    ]


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
            
    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ [AUTH] Eroare citire service_account.json local: {e}", flush=True)

    print("❌ [AUTH] Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def curata_toate_discurile():
    service = get_drive_service()

    if not FOLDERE_XML_IDS:
        print("🛑 [EROARE CRITICĂ] Lista FOLDERE_XML_IDS este goală!", flush=True)
        sys.exit(1)

    print("============================================================", flush=True)
    print(f"⚠️ PORNIRE CURĂȚENIE TOTALĂ PE {len(FOLDERE_XML_IDS)} SHARED DRIVE-URI", flush=True)
    print("============================================================", flush=True)

    total_sterse = 0

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
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
                    print(f"   ✨ Folderul este deja gol sau nu s-au găsit fișiere.", flush=True)
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
                            print(f"   🗑️ Șterse până acum pe Drive #{idx}: {sterse_drive:,} fișiere...", flush=True)

                    except Exception as e_del:
                        print(f"   ⚠️ Eroare ștergere fișier {f['name']} ({f['id']}): {e_del}", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            except Exception as e:
                print(f"❌ Eroare la scanarea Drive #{idx}: {e}", flush=True)
                break

        print(f"✅ Drive #{idx} curățat! Total fișiere șterse: {sterse_drive:,}", flush=True)

    # Ștergere locală a indexului master vechi
    cale_index = RADACINA_PROIECT / "index_xml.json.gz"
    if cale_index.exists():
        cale_index.unlink()
        print("\n🗑️ Fișierul local index_xml.json.gz a fost șters.", flush=True)

    print("\n============================================================", flush=True)
    print(f"🏁 CURĂȚENIE TOTALĂ FINALIZATĂ! Total fișiere eliminate: {total_sterse:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    curata_toate_discurile()
