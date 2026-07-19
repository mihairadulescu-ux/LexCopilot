import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Suportă string cu ID-uri separate prin virgulă
TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")

def obtine_drive():
    print("🔑 [Reset XML] Conectare Google Drive...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipsește secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def reseteaza_atribute_xml():
    if not TARGET_FOLDERS_RAW:
        print("🛑 Eroare configurare: DRIVE_FOLDER_XML lipsește din mediu!")
        return

    folder_ids = [fid.strip() for fid in TARGET_FOLDERS_RAW.split(",") if fid.strip()]
    service = obtine_drive()
    print(f"📂 Inițiere resetare pe {len(folder_ids)} Shared Drive-uri mapate...")

    fisiere_marcate = []
    
    for folder_id in folder_ids:
        print(f"🔍 Scanare folder XML (ID: {folder_id})...")
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"
        
        while True:
            try:
                # corpora="allDrives" este obligatoriu când interogăm parents pe Shared Drive fără driveId dedicat
                response = service.files().list(
                    q=query, 
                    fields="nextPageToken, files(id, name, description)", 
                    pageToken=page_token, 
                    pageSize=1000,
                    supportsAllDrives=True, 
                    includeItemsFromAllDrives=True,
                    corpora="allDrives"
                ).execute()
                
                fișiere = response.get("files", [])
                
                for f in fișiere:
                    nume = f.get('name', '').lower()
                    descriere = f.get('description', '')
                    if nume.endswith('.xml') and descriere == "processed_for_tags: true":
                        fisiere_marcate.append(f)
                        
                page_token = response.get("nextPageToken", None)
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Nu s-a putut scana folderul {folder_id}: {e}")
                break

    if not fisiere_marcate:
        print("✨ Nu s-a găsit niciun XML marcat în locațiile verificate. Totul este pregătit fresh!")
        return

    print(f"⚙️ Am găsit în total {len(fisiere_marcate)} fișiere marcate. Începe curățarea metadatelor...")
    for idx, xml in enumerate(fisiere_marcate, 1):
        try:
            service.files().update(
                fileId=xml["id"], 
                body={"description": ""}, 
                supportsAllDrives=True
            ).execute()
            
            if idx % 100 == 0 or idx == len(fisiere_marcate):
                print(f"    ✅ [{idx}/{len(fisiere_marcate)}] Resetat cu succes: {xml['name']}")
        except Exception as e:
            continue

    print("\n🚀 Resetare completă pe toate Shared Drive-urile!")

if __name__ == "__main__":
    reseteaza_atribute_xml()
