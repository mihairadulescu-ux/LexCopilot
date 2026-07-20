import os
import re
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")
FOLDER_IDS = []

if TARGET_FOLDERS_RAW.strip():
    clean_raw = TARGET_FOLDERS_RAW.replace('"', '').replace("'", "").replace("\n", "").replace("\r", "").strip()
    FOLDER_IDS = [fid.strip() for fid in clean_raw.split(",") if fid.strip()]

if not FOLDER_IDS:
    FOLDER_IDS = [
        "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
        "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
        "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
        "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
    ]

def get_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul '{credentials_path}'!")
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def construieste_index():
    service = get_drive_service()
    index_pe_ani = {}
    CHUNK_SIZE = 1000
    regex_an = re.compile(r"brut_legislatie_(\d{4})_")

    print(f"{GALBEN}🔍 [Indexare Drive] scanare unică globală peste directoare...{RESET}", flush=True)

    for folder_id in FOLDER_IDS:
        page_token = None
        query = f"'{folder_id}' in parents and name sw 'brut_legislatie_' and trashed = false"

        try:
            while True:
                response = service.files().list(
                    q=query,
                    spaces='drive',
                    fields='nextPageToken, files(id, name, description)',
                    pageSize=CHUNK_SIZE,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                files = response.get('files', [])
                for f in files:
                    match = regex_an.search(f['name'])
                    if match:
                        an = match.group(1)
                        if an not in index_pe_ani:
                            index_pe_ani[an] = []
                        index_pe_ani[an].append({
                            "id": f['id'],
                            "name": f['name'],
                            "description": f.get('description', '')
                        })

                page_token = response.get('nextPageToken', None)
                if not page_token:
                    break
        except Exception as e:
            print(f"{ROSU}⚠️ Eroare scanare folder {folder_id[:8]}: {e}{RESET}", flush=True)

    with open("index_fisiere.json", "w", encoding="utf-8") as f:
        json.dump(index_pe_ani, f, indent=2)

    total_fisiere = sum(len(v) for v in index_pe_ani.values())
    print(f"{VERDE}✅ [Index Salvat] Am indexat {total_fisiere} fișiere distribuite pe {len(index_pe_ani)} ani!{RESET}", flush=True)

if __name__ == "__main__":
    construieste_index()
