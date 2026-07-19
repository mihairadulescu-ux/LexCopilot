import os
import json
import time
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")


def obtine_drive():
    print("🔑 [Reset XML] Conectare Google Drive...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipsește secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def reseteaza_atribute_xml():
    if not TARGET_FOLDERS_RAW:
        print(f"{ROSU}🛑 Eroare configurare: DRIVE_FOLDER_XML lipsește din mediu!{RESET}")
        return

    folder_ids = [fid.strip() for fid in TARGET_FOLDERS_RAW.split(",") if fid.strip()]
    service = obtine_drive()
    print(f"{VERDE}📂 Inițiere resetare pe {len(folder_ids)} locații...{RESET}")

    fisiere_marcate = []
    
    for folder_id in folder_ids:
        print(f"🔍 Scanare folder XML (ID: {folder_id})...")
        page_token = None
        
        # Sintaxa nativă stabilă pentru proprietățile aplicației
        query = (
            f"'{folder_id}' in parents and name contains '.xml' and "
            f"appProperties has {{ key='processed' and value='true' }} and trashed = false"
        )
        
        while True:
            try:
                response = service.files().list(
                    q=query, 
                    spaces='drive',
                    fields="nextPageToken, files(id, name)", 
                    pageToken=page_token, 
                    pageSize=1000,
                    supportsAllDrives=True, 
                    includeItemsFromAllDrives=True
                ).execute()
                
                fisiere_marcate.extend(response.get("files", []))
                page_token = response.get("nextPageToken", None)
                if not page_token:
                    break
            except Exception as e:
                print(f"{ROSU}⚠️ Eroare scanare folder {folder_id}: {e}{RESET}")
                break

    if not fisiere_marcate:
        print(f"{VERDE}✨ Nu s-a găsit niciun XML marcat ca procesat. Totul este curat în Cloud!{RESET}")
        return

    total_fisiere = len(fisiere_marcate)
    print(f"{GALBEN}⚙️ Am găsit în total {total_fisiere} fișiere procesate. Începe ștergerea flag-urilor...{RESET}", flush=True)
    
    for idx, xml in enumerate(fisiere_marcate, 1):
        try:
            # Trecem proprietatea pe 'false' ca să poată fi re-procesat
            service.files().update(
                fileId=xml["id"], 
                body={"appProperties": {"processed": "false"}}, 
                supportsAllDrives=True
            ).execute()
            
            if idx % 10 == 0 or idx == total_fisiere:
                print(f"    ✅ [{idx}/{total_fisiere}] Resetat flag processed pentru: {xml['name']}", flush=True)
        except Exception as e:
            print(f"{ROSU}⚠️ Eroare resetare la fișierul {xml['name']}: {e}{RESET}", flush=True)
            continue

    print(f"\n{VERDE}🎉 [SUCCES] Resetare finalizată!{RESET}\n")


if __name__ == "__main__":
    reseteaza_atribute_xml()
