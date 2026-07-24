import os
import sys
import json
import time
from pathlib import Path

# Unbuffered logging pentru GitHub Actions Live Stream
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

# Citire strictă index transmis din CLI (ex: python redenumeste_fisiere_drive.py 3)
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


def curata_fisiere_pe_drive():
    service = get_drive_service()
    total_discuri = len(FOLDERE_XML_IDS)

    # SELECȚIE STRICTĂ A DISCULUI (identică cu scriptul tău original)
    if INDEX_DRIVE_TARGET is not None:
        idx_zero = INDEX_DRIVE_TARGET - 1
        if 0 <= idx_zero < total_discuri:
            folder_id_target = FOLDERE_XML_IDS[idx_zero]
            discuri_de_procesat = [(INDEX_DRIVE_TARGET, folder_id_target)]
            print("============================================================", flush=True)
            print(f"🧹 [CURĂȚENIE TOTALĂ] FIXAT STRICT PE DRIVE #{INDEX_DRIVE_TARGET} din {total_discuri}", flush=True)
            print(f"📂 Folder ID direct: {folder_id_target}", flush=True)
            print("============================================================", flush=True)
        else:
            print(f"❌ Indexul {INDEX_DRIVE_TARGET} este invalid! Există doar {total_discuri} discuri.", flush=True)
            return
    else:
        discuri_de_procesat = list(enumerate(FOLDERE_XML_IDS, start=1))
        print("============================================================", flush=True)
        print(f"🧹 [CURĂȚENIE TOTALĂ] PROCESARE TOATE CELE {total_discuri} DISCURI", flush=True)
        print("============================================================", flush=True)

    total_evaluate = 0
    total_sterse = 0

    for idx, folder_id in discuri_de_procesat:
        page_token = None
        count_drive_sterse = 0

        while True:
            try:
                # Citim pachete de fișiere neșterse
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    spaces='drive',
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=500,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = response.get('files', [])
                if not files:
                    print(f"✨ Drive-ul #{idx} este complet gol.", flush=True)
                    break

                for f in files:
                    nume = f['name']
                    total_evaluate += 1

                    # ȘTERGERE DEFINITIVĂ (cu fallback pe Trash dacă nu permite dreptul)
                    try:
                        service.files().delete(
                            fileId=f['id'],
                            supportsAllDrives=True,
                            supportsTeamDrives=True
                        ).execute()

                        total_sterse += 1
                        count_drive_sterse += 1

                        if total_sterse % 100 == 0 or total_sterse == 1:
                            print(f"   🗑️ [{total_sterse:,}] Șters de pe Drive #{idx}: '{nume}'", flush=True)

                    except Exception:
                        try:
                            # Fallback: mutare în Coșul de gunoi
                            service.files().update(
                                fileId=f['id'],
                                body={'trashed': True},
                                supportsAllDrives=True,
                                supportsTeamDrives=True
                            ).execute()
                            total_sterse += 1
                            count_drive_sterse += 1
                            if total_sterse % 100 == 0 or total_sterse == 1:
                                print(f"   🗑️ [{total_sterse:,}] Mutat în Trash pe Drive #{idx}: '{nume}'", flush=True)
                        except Exception as e_trash:
                            print(f"   ⚠️ Eroare eliminare {f['id']} ({nume}): {e_trash}", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            except Exception as e:
                print(f"⚠️ Eroare la scanare Drive #{idx} ({folder_id}): {e}", flush=True)
                break

        print(f"✅ Shared Drive #{idx} finalizat! Total fișiere eliminate: {count_drive_sterse:,}", flush=True)

    print("\n============================================================", flush=True)
    print(f"🏁 FINALIZAT CURĂȚENIA PENTRU DRIVE #{INDEX_DRIVE_TARGET if INDEX_DRIVE_TARGET else 'TOATE'}!", flush=True)
    print(f"📊 Evaluat: {total_evaluate:,} | Total Eliminate: {total_sterse:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    curata_fisiere_pe_drive()
