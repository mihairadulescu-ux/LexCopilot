import os
import sys
import json
from pathlib import Path

# Stream live unbuffered pentru GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from google.oauth2 import service_account
from googleapiclient.discovery import build

# LISTA TA REALĂ DE DRIVE-URI (puse și ca fallback direct în cod)
RAW_DRIVE_STRING = os.getenv("DRIVE_FOLDER_XML") or (
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m,"
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1,"
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5,"
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2,"
    "1JTf2oO_pBBYqWJv-FNoM8xy55uYCB7cX,"
    "1_9c6ikq6SMGOBv6UNHN2zfl_WWcuid7v,"
    "1kLmRsgMwM00TOQXzvJuK4YwJ6FJeLRxB"
)

# Parsăm lista curată de ID-uri (split după virgulă)
FOLDERE_XML_IDS = [fid.strip() for fid in RAW_DRIVE_STRING.split(",") if fid.strip()]


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

    print("============================================================", flush=True)
    print(f"⚠️ PORNIRE CURĂȚENIE TOTALĂ PE CELE {len(FOLDERE_XML_IDS)} SHARED DRIVE-URI REALE", flush=True)
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
                    print(f"   ✨ Drive-ul #{idx} este deja gol.", flush=True)
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
                        print(f"   ⚠️ Eroare la ștergerea fișierului {f['name']}: {e_del}", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            except Exception as e:
                print(f"❌ Eroare la scanarea Drive #{idx}: {e}", flush=True)
                break

        print(f"✅ Drive #{idx} curățat complet! Total fișiere șterse: {sterse_drive:,}", flush=True)

    print("\n============================================================", flush=True)
    print(f"🏁 CURĂȚENIE TOTALĂ FINALIZATĂ! Total fișiere eliminate: {total_sterse:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    curata_toate_discurile_reale()
