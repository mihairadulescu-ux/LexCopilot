import os
import sys
import json
from pathlib import Path

# Unbuffered stream - mesaje directe pe ecran
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from drive_config import FOLDERE_XML_IDS

# Preluăm discul țintă din comandă (dacă există)
INDEX_DRIVE_TARGET = None
if len(sys.argv) >= 2 and sys.argv[1].isdigit():
    INDEX_DRIVE_TARGET = int(sys.argv[1])


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
            print(f"❌ [AUTH] Eroare parsare JSON: {e}", flush=True)
            sys.exit(1)
            
    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ [AUTH] Eroare citire locală: {e}", flush=True)

    print("❌ [AUTH] Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def curata_fisiere():
    service = get_drive_service()
    total_discuri = len(FOLDERE_XML_IDS)

    if INDEX_DRIVE_TARGET is not None:
        idx_zero = INDEX_DRIVE_TARGET - 1
        if 0 <= idx_zero < total_discuri:
            discuri_de_procesat = [(INDEX_DRIVE_TARGET, FOLDERE_XML_IDS[idx_zero])]
            print(f"🧹 [START] Ștergere strictă pe Drive #{INDEX_DRIVE_TARGET}...", flush=True)
        else:
            print(f"❌ Index {INDEX_DRIVE_TARGET} invalid!", flush=True)
            return
    else:
        discuri_de_procesat = list(enumerate(FOLDERE_XML_IDS, start=1))
        print(f"🧹 [START] Ștergere pe TOATE cele {total_discuri} discuri...", flush=True)

    total_sterse = 0

    for idx, folder_id in discuri_de_procesat:
        print(f"\n📂 Procesare Drive #{idx} (ID: {folder_id})...", flush=True)
        page_token = None
        sterse_pe_disc = 0

        while True:
            try:
                # Citim fișierele neșterse
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    spaces='drive',
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=200,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = response.get('files', [])
                if not files:
                    print(f"✨ Drive #{idx} este curat/gol.", flush=True)
                    break

                print(f"   🔎 Am găsit {len(files)} fișiere în lot. Se șterg...", flush=True)

                for f in files:
                    try:
                        # Comanda de ștergere directă
                        service.files().delete(
                            fileId=f['id'],
                            supportsAllDrives=True,
                            supportsTeamDrives=True
                        ).execute()
                        
                        total_sterse += 1
                        sterse_pe_disc += 1

                        if sterse_pe_disc % 50 == 0:
                            print(f"   🗑️ [Drive #{idx}] Șterse {sterse_pe_disc:,} fișiere...", flush=True)

                    except Exception as e_del:
                        # Fallback în caz că nu permite delete definitiv
                        try:
                            service.files().update(
                                fileId=f['id'],
                                body={'trashed': True},
                                supportsAllDrives=True,
                                supportsTeamDrives=True
                            ).execute()
                            total_sterse += 1
                            sterse_pe_disc += 1
                        except Exception:
                            pass

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            except Exception as e:
                print(f"⚠️ Eroare scanare Drive #{idx}: {e}", flush=True)
                break

        print(f"✅ Drive #{idx} curățat! Total șterse: {sterse_pe_disc:,}", flush=True)

    print("\n============================================================", flush=True)
    print(f"🏁 CURĂȚENIE FINALIZATĂ! Total fișiere eliminate: {total_sterse:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    curata_fisiere()
