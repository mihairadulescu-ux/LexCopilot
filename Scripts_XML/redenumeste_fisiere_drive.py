import os
import sys
import json
import time
from pathlib import Path

# Stream direct ne-bufferat (Live pe GitHub Actions)
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
            print(f"❌ [AUTH] Eroare JSON: {e}", flush=True)
            sys.exit(1)
            
    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ [AUTH] Eroare local: {e}", flush=True)

    print("❌ [AUTH] Lipsă secret GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def curata_masiv_batch():
    service = get_drive_service()
    total_discuri = len(FOLDERE_XML_IDS)

    if INDEX_DRIVE_TARGET is not None:
        idx_zero = INDEX_DRIVE_TARGET - 1
        if 0 <= idx_zero < total_discuri:
            discuri = [(INDEX_DRIVE_TARGET, FOLDERE_XML_IDS[idx_zero])]
        else:
            print(f"❌ Disc {INDEX_DRIVE_TARGET} invalid!", flush=True)
            return
    else:
        discuri = list(enumerate(FOLDERE_XML_IDS, start=1))

    print("============================================================", flush=True)
    print(f"⚡ PORNIRE ȘTERGERE RAPIDĂ ÎN BATCH (PACHETE DE 100)", flush=True)
    print("============================================================", flush=True)

    total_sterse = 0

    for idx, folder_id in discuri:
        print(f"\n📂 Curățare Drive #{idx} ({folder_id})...", flush=True)
        sterse_pe_disc = 0
        page_token = None

        while True:
            try:
                # Interogăm pachete de câte 100
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    spaces='drive',
                    fields="nextPageToken, files(id)",
                    pageToken=page_token,
                    pageSize=100,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = response.get('files', [])
                if not files:
                    print(f"✨ Drive #{idx} este 100% gol!", flush=True)
                    break

                # CREĂM CEREREA BATCH (Toate 100 nimeresc într-un singur pachet HTTP)
                batch = service.new_batch_http_request()

                def callback(request_id, response, exception):
                    nonlocal sterse_pe_disc, total_sterse
                    if exception is None:
                        sterse_pe_disc += 1
                        total_sterse += 1

                for f in files:
                    batch.add(
                        service.files().delete(
                            fileId=f['id'],
                            supportsAllDrives=True,
                            supportsTeamDrives=True
                        ),
                        callback=callback
                    )

                # Executăm tot pachetul dintr-o singură mișcare
                batch.execute()
                print(f"   🔥 [Drive #{idx}] Eliminat lot de {len(files)} fișiere... Total șterse pe disc: {sterse_pe_disc:,}", flush=True)

                # Pauză de 0.2s anti-flood
                time.sleep(0.2)

            except Exception as e:
                print(f"⚠️ Eroare la lotul curent: {e}", flush=True)
                time.sleep(1)
                page_token = response.get('nextPageToken') if 'response' in locals() else None
                if not page_token:
                    break

        print(f"✅ Drive #{idx} curățat complet! Total șterse: {sterse_pe_disc:,}", flush=True)

    print("\n============================================================", flush=True)
    print(f"🏁 CURĂȚENIE TOTALĂ CU SUCCES! Total eliminate: {total_sterse:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    curata_masiv_batch()
