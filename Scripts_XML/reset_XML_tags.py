import os
import sys
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

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
    if not os.path.exists("index_fisiere.json"):
        print(f"{ROSU}🛑 Eroare Reset: Nu s-a găsit fișierul 'index_fisiere.json'!{RESET}")
        sys.exit(1)

    with open("index_fisiere.json", "r", encoding="utf-8") as f:
        index_data = json.load(f)

    print(f"\n{GALBEN}⚙️ [Reset] Pornire resetare pe bază de index pentru anii {ani_procesare}...{RESET}", flush=True)
    
    contor_reset = 0
    for target_year in ani_procesare:
        fisiere_an = index_data.get(str(target_year), [])
        
        for file_info in fisiere_an:
            # Resetăm doar ce este deja marcat ca processed=true în descriere (sau în index)
            if file_info.get("description") == "processed=true":
                try:
                    service.files().update(
                        fileId=file_info["id"],
                        body={"description": "processed=false"},
                        fields="id",
                        supportsAllDrives=True
                    ).execute()
                    contor_reset += 1
                except Exception as e:
                    print(f"{ROSU}⚠️ Eroare reset pe fișierul {file_info['name']}: {e}{RESET}", flush=True)

    print(f"{VERDE}✅ [Reset Gata] Pentru anii {ani_procesare} au fost resetate {contor_reset} fișiere.{RESET}", flush=True)

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
