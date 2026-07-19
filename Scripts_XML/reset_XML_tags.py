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

def ruleaza_reset_flaguri(service, ani_procesare):
    for target_year in ani_procesare:
        print(f"\n{GALBEN}⚙️ [Reset] Scanare fișiere de curățat pentru anul {target_year}...{RESET}")
        fișiere_de_resetat = []

        for folder_id in FOLDER_IDS:
            page_token = None
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_{target_year}_pag' and trashed = false"

            try:
                while True:
                    response = service.files().list(
                        q=query, 
                        spaces='drive', 
                        fields='nextPageToken, files(id, name)',
                        pageSize=1000,
                        pageToken=page_token,
                        supportsAllDrives=True, 
                        includeItemsFromAllDrives=True
                    ).execute()

                    fișiere_de_resetat.extend(response.get('files', []))
                    page_token = response.get('nextPageToken', None)
                    if not page_token:
                        break
            except Exception as e:
                continue

        total_fișiere = len(fișiere_de_resetat)
        print(f"{VERDE}🎯 Identificate {total_fișiere} fișiere XML în total pentru anul {target_year}.{RESET}")

        if total_fișiere == 0:
            continue

        print(f"🔄 Se resetează metadatele (processed=false) pentru cele {total_fișiere} fișiere...")
        for idx_f, f in enumerate(fișiere_de_resetat, 1):
            if idx_f % 250 == 0 or idx_f == total_fișiere:
                print(f"   [Progres Reset] {idx_f}/{total_fișiere} modificate...")
                
            try:
                service.files().update(
                    fileId=f['id'],
                    body={'description': 'processed=false'},
                    fields='id',
                    supportsAllDrives=True
                ).execute()
            except Exception as e:
                continue
                
        print(f"{VERDE}✅ Anul {target_year} a fost resetat complet pe toate cele 4 discuri.{RESET}")

if __name__ == "__main__":
    argumente_numerice = []
    for arg in sys.argv[1:]:
        piese = arg.split()
        for piesa in piese:
            if piesa.isdigit():
                argumente_numerice.append(int(piesa))

    if not argumente_numerice:
        print(f"{ROSU}🛑 Eroare Reset: Lipsesc anii ca parametru!{RESET}")
        sys.exit(1)
        
    drive_service = get_drive_service()
    ruleaza_reset_flaguri(drive_service, argumente_numerice)
