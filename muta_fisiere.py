import os
import sys
import json
import time
import random
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

def copiaza_tot():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE CRITICĂ: DRIVE_FOLDER_PDF nu este setat în GitHub Variables!")
        sys.exit(1)

    print(f"🔄 Se pregătește copierea fișierelor direct pe serverele Google...")
    print(f"📂 Din folderul sursă: {ORIGIN_FOLDER_ID}")
    print(f"📂 În noul Shared Drive de destinație: {TARGET_FOLDER_ID}")

    try:
        service = obtine_drive()
        page_token = None
        copiat_count = 0
        
        # Query: căutăm fișierele din folderul vechi care nu sunt șterse
        query = f"'{ORIGIN_FOLDER_ID}' in parents and trashed = false"
        
        while True:
            # Folosim corpora="user" deoarece sursa este în Personal Drive-ul tău, nu în noul Shared Drive
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
                print("ℹ️ Nu s-au mai găsit fișiere de copiat în folderul sursă.")
                break
                
            for f in files:
                file_id = f["id"]
                name = f["name"]
                
                # Evităm copierea fișierelor de sistem sau temporare dacă există
                if name.startswith(".") or name == "desktop.ini":
                    continue
                    
                try:
                    # Copiere directă de la server la server
                    copie_metadata = {
                        'name': name,
                        'parents': [TARGET_FOLDER_ID]
                    }
                    
                    service.files().copy(
                        fileId=file_id,
                        body=copie_metadata,
                        supportsAllDrives=True  # OBLIGATORIU pentru destinația în Shared Drive
                    ).execute()
                    
                    copiat_count += 1
                    
                    # Log-uri mai aerisite ca să nu aglomerăm consola
                    if copiat_count % 50 == 0:
                        print(f"✅ [Progres] Am copiat {copiat_count} fișiere... (Ultimul: {name})", flush=True)
                    else:
                        print(f"✅ Copiat: {name}", flush=True)
                        
                    # O mică pauză de bun simț pentru a evita rate-limiting-ul pe API-ul de copy
                    time.sleep(random.uniform(0.1, 0.3))
                        
                except Exception as e:
                    print(f"❌ Eroare la copierea fișierului {name}: {e}", flush=True)
                    
            page_token = response.get("nextPageToken", None)
            if not page_token:
                break

        print(f"\n🎉 OPERAȚIUNE FINALIZATĂ!")
        print(f"📊 Total fișiere copiate în noul Shared Drive: {copiat_count}")
        print("🧹 Acum poți șterge liniștit manual conținutul din folderul vechi din interfața web.")

    except Exception as e:
        print(f"🛑 Eroare generală la execuție API: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    copiaza_tot()
