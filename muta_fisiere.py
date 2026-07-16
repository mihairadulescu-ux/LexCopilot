import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Citim ID-urile direct din variabilele GitHub și din secrets
ORIGIN_FOLDER_ID = "1c8SEo8UrQVe6qgzPFGLXJFiMyLeI-r8D"  # Folderul vechi (surse PDF brute)
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")        # Noul tău Shared Drive definit în GitHub Variables

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def muta_tot():
    if not TARGET_FOLDER_ID:
        print("❌ Eroare: Nu s-a găsit variabila DRIVE_FOLDER_PDF în setările GitHub!")
        return

    print(f"🔄 Se pregătește mutarea fișierelor...")
    print(f"📂 Din folderul vechi: {ORIGIN_FOLDER_ID}")
    print(f"📂 În noul Shared Drive: {TARGET_FOLDER_ID}")

    service = obtine_drive()
    page_token = None
    mutat_count = 0
    
    while True:
        # Căutăm fișierele din folderul vechi
        query = f"'{ORIGIN_FOLDER_ID}' in parents and trashed = false"
        response = service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name)", 
            pageToken=page_token, 
            pageSize=100,
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
        ).execute()
        
        files = response.get("files", [])
        if not files:
            break
            
        for f in files:
            file_id = f["id"]
            name = f["name"]
            try:
                # Mutarea se face instantaneu pe serverele Google prin API update
                service.files().update(
                    fileId=file_id,
                    addParents=TARGET_FOLDER_ID,
                    removeParents=ORIGIN_FOLDER_ID,
                    fields="id, parents",
                    supportsAllDrives=True
                ).execute()
                print(f"✅ Mutat cu succes: {name}", flush=True)
                mutat_count += 1
            except Exception as e:
                print(f"❌ Eroare la mutarea {name}: {e}", flush=True)
                
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break

    print(f"\n🎉 Operațiune finalizată! Total fișiere mutate pe serverele Google: {mutat_count}")

if __name__ == "__main__":
    muta_tot()
