import os
import sys
import json
import csv
from google.oauth2 import service_account
from googleapiclient.discovery import build

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")
FOLDER_IDS = [fid.strip() for fid in TARGET_FOLDERS_RAW.replace('"', '').replace("'", "").split(",") if fid.strip()] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
]

def get_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if github_secret:
        creds = service_account.Credentials.from_service_account_info(json.loads(github_secret), scopes=scopes)
    else:
        creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def construieste_index_global():
    service = get_drive_service()
    index_fisiere = []

    print(f"🔍 [Indexare Drive] Pornire scanare unică globală peste cele 4 directoare...", flush=True)

    for idx_folder, folder_id in enumerate(FOLDER_IDS, start=1):
        print(f"\n{GALBEN}📂 Scanare Folder {idx_folder}/{len(FOLDER_IDS)} (ID: {folder_id[:8]}...){RESET}", flush=True)
        
        page_token = None
        contor_folder = 0
        query = f"'{folder_id}' in parents and name contains 'brut_legislatie_' and trashed = false"
        
        try:
            while True:
                response = service.files().list(
                    q=query,
                    spaces='drive',
                    fields='nextPageToken, files(id, name, description)',
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                files = response.get('files', [])
                if not files:
                    break

                for f in files:
                    index_fisiere.append({
                        'id': f['id'],
                        'name': f['name'],
                        'description': f.get('description', ''),
                        'folder_id': folder_id
                    })
                    contor_folder += 1

                # UPDATE PERIODIC: Afișăm progresul la fiecare 2.000 de fișiere găsite per folder
                if contor_folder % 2000 == 0:
                    print(f"   ⚡ Progres Folder {folder_id[:8]}: {contor_folder} fișiere indexate până acum... (Total global: {len(index_fisiere)})", flush=True)

                page_token = response.get('nextPageToken', None)
                if not page_token:
                    break
                    
            print(f"✅ [Folder Finalizat] Gasite {contor_folder} fișiere în folderul {folder_id[:8]}.", flush=True)

        except Exception as e:
            print(f"{ROSU}⚠️ Eroare scanare folder {folder_id[:8]}: {e}{RESET}", flush=True)

    # Salvare în fișier local
    with open("index_xml.json", "w", encoding="utf-8") as f:
        json.dump(index_fisiere, f, ensure_ascii=False, indent=2)

    ani_gasiti = set()
    for item in index_fisiere:
        piese = item['name'].split('_')
        if len(piese) >= 3 and piese[2].isdigit():
            ani_gasiti.add(piese[2])

    print(f"\n{VERDE}🏁 [Index Finalizat] Am salvat 'index_xml.json' cu {len(index_fisiere)} fișiere din {len(ani_gasiti)} ani diferiți!{RESET}", flush=True)

if __name__ == "__main__":
    construieste_index_global()
