import os
import sys
import json
from pathlib import Path

# Stream unbuffered
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from google.oauth2 import service_account
from googleapiclient.discovery import build

# LISTA CU CELE 7 SHARED DRIVE-URI / FOLDERE XML
FOLDERE_XML_IDS = [
    "1O9c1S2_48gG1IqX3hGzO8e0Z",  # Dacă ai alte ID-uri în proiect, le poți actualiza aici
    "1-08A0Apt2qfO3-yR306uY1-k-S52cE-c",
    "1-0P3O6v8YxL7_1_1234567890abcdef", # Pune ID-urile tale reale dacă sunt altele
]

# Sau dacă ID-ul principal era doar unul în mediul vechi:
FOLDER_SINGLE = os.getenv("DRIVE_FOLDER_XML") or os.getenv("GDRIVE_FOLDER_ID")
if FOLDER_SINGLE and FOLDER_SINGLE not in FOLDERE_XML_IDS:
    FOLDERE_XML_IDS.append(FOLDER_SINGLE)


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
            
    print("❌ [AUTH] Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON în mediu!", flush=True)
    sys.exit(1)


def curata_tot_independent():
    service = get_drive_service()

    print("============================================================", flush=True)
    print("⚠️ PORNIRE CURĂȚENIE TOTALĂ FĂRĂ DEPENDINȚE (DIRECT GOOGLE DRIVE)", flush=True)
    print("============================================================", flush=True)

    total_sterse = 0

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n📂 Curățare Folder/Drive #{idx} (ID: {folder_id})...", flush=True)
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

    print("\n============================================================", flush=True)
    print(f"🏁 CURĂȚENIE TOTALĂ FINALIZATĂ! Total fișiere eliminate: {total_sterse:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    curata_tot_independent()
