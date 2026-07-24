import os
import sys
import json
import time

# Forțăm afișarea instantanee pe ecran (fără buffer)
os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("------------------------------------------------------------", flush=True)
print("🚀 SCRIPTUL A PORNIT! (TEST CONSOLĂ ONLINE)", flush=True)
print("------------------------------------------------------------", flush=True)

from google.oauth2 import service_account
from googleapiclient.discovery import build

RAW_DRIVE_STRING = os.getenv("DRIVE_FOLDER_XML") or (
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m,"
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1,"
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5,"
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2,"
    "1JTf2oO_pBBYqWJv-FNoM8xy55uYCB7cX,"
    "1_9c6ikq6SMGOBv6UNHN2zfl_WWcuid7v,"
    "1kLmRsgMwM00TOQXzvJuK4YwJ6FJeLRxB"
)

FOLDERE_XML_IDS = [fid.strip() for fid in RAW_DRIVE_STRING.split(",") if fid.strip()]


def get_drive_service():
    print("🔑 Autentificare Google Service Account...", flush=True)
    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )
    if not creds_json:
        print("❌ EROARE: Secretul GOOGLE_SERVICE_ACCOUNT_JSON nu a fost găsit!", flush=True)
        sys.exit(1)

    try:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        print("✅ Autentificare reușită!", flush=True)
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        print(f"❌ Eroare la autentificare: {e}", flush=True)
        sys.exit(1)


def curata_drive_batch():
    service = get_drive_service()

    print(f"\n📂 Am identificat {len(FOLDERE_XML_IDS)} discuri de curățat.", flush=True)
    total_sterse_proiect = 0

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n------------------------------------------------------------", flush=True)
        print(f"📂 [Drive #{idx}/{len(FOLDERE_XML_IDS)}] Scanare ID: {folder_id}", flush=True)
        print(f"------------------------------------------------------------", flush=True)

        sterse_folder = 0

        while True:
            try:
                # Interogăm câte 100 de fișiere o dată
                res = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    spaces='drive',
                    fields="nextPageToken, files(id, name)",
                    pageSize=100,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = res.get('files', [])

                if not files:
                    print(f"✨ Drive-ul #{idx} este complet curat (0 fișiere rămase).", flush=True)
                    break

                print(f"   🔎 Găsit lot de {len(files)} fișiere. Trimitere comanda BATCH delete...", flush=True)

                # Ștergere BATCH (Grupăm 100 de comenzi într-o singură cerere HTTP)
                batch = service.new_batch_http_request()

                def callback_stergere(request_id, response, exception):
                    nonlocal sterse_folder, total_sterse_proiect
                    if exception is None:
                        sterse_folder += 1
                        total_sterse_proiect += 1
                    else:
                        print(f"   ⚠️ Eroare pe fișier: {exception}", flush=True)

                for f in files:
                    batch.add(
                        service.files().delete(
                            fileId=f['id'],
                            supportsAllDrives=True,
                            supportsTeamDrives=True
                        ),
                        callback=callback_stergere
                    )

                batch.execute()
                print(f"   🗑️ Progres pe Drive #{idx}: {sterse_folder:,} fișiere șterse până acum.", flush=True)

                # Pauză scurtă anti-rate-limit
                time.sleep(0.5)

            except Exception as e:
                print(f"❌ Eroare/Timeout pe Drive #{idx}: {e}", flush=True)
                time.sleep(2)
                break

        print(f"✅ Drive #{idx} finalizat! Total șterse pe acest disc: {sterse_folder:,}", flush=True)

    print("\n============================================================", flush=True)
    print(f"🏁 CURĂȚENIE TOTALĂ FINALIZATĂ! Total fișiere eliminate: {total_sterse_proiect:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    curata_drive_batch()
