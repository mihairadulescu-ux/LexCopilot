import os
import sys
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Folderul vechi (Personal Drive / Folder sursă)
ORIGIN_FOLDER_ID = "1c8SEo8UrQVe6qgzPFGLXJFiMyLeI-r8D"  
# Noul tău Shared Drive (preluat din GitHub Variables)
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")        

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def muta_tot():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE CRITICĂ: DRIVE_FOLDER_PDF nu este setat în GitHub Variables!")
        sys.exit(1)

    print(f"🔄 Se pregătește mutarea fișierelor direct pe serverele Google...")
    print(f"📂 Din folderul sursă: {ORIGIN_FOLDER_ID}")
    print(f"📂 În noul Shared Drive de destinație: {TARGET_FOLDER_ID}")

    try:
        service = obtine_drive()
        page_token = None
        mutat_count = 0
        
        # Query: căutăm fișierele din folderul vechi
        query = f"'{ORIGIN_FOLDER_ID}' in parents and trashed = false"
        
        while True:
            # Schimbat corpora="user" pentru a putea scana folderul sursă aflat în afara noului Shared Drive
            response = service.files().list(
                q=query, 
                fields="nextPageToken, files(id, name)", 
                pageToken=page_token, 
                pageSize=100,
                supportsAllDrives=True, 
                includeItemsFromAllDrives=True,
                corpora="user"
            ).execute()
            
            files = response.get("files", [])
            if not files:
                print("ℹ️ Nu s-au mai găsit fișiere de mutat în folderul sursă.")
                break
                
            for f in files:
                file_id = f["id"]
                name = f["name"]
                try:
                    # Mutarea se face instataneu pe serverele Google (metadate)
                    service.files().update(
                        fileId=file_id,
                        addParents=TARGET_FOLDER_ID,
                        removeParents=ORIGIN_FOLDER_ID,
                        fields="id, parents",
                        supportsAllDrives=True  # OBLIGATORIU pentru Shared Drive
                    ).execute()
                    
                    mutat_count += 1
                    if mutat_count % 100 == 0:
                        print(f"✅ [Progres] Am mutat {mutat_count} fișiere... (Ultimul: {name})", flush=True)
                    else:
                        print(f"✅ Mutat: {name}", flush=True)
                        
                except Exception as e:
                    print(f"❌ Eroare la mutarea fișierului {name}: {e}", flush=True)
                    
            page_token = response.get("nextPageToken", None)
            if not page_token:
                break

        print(f"\n🎉 OPERAȚIUNE FINALIZATĂ!")
        print(f"📊 Total fișiere mutate: {mutat_count}")

    except Exception as e:
        print(f"🛑 Eroare generală la execuție API: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    muta_tot()
