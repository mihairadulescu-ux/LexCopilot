import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_XML")

def obtine_drive():
    print("🔑 [Reset XML] Conectare Google Drive...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipsește secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def reseteaza_atribute_xml():
    if not TARGET_FOLDER_ID:
        print("🛑 Eroare configurare: DRIVE_FOLDER_XML lipseste din mediu!")
        return

    service = obtine_drive()
    print(f"📂 Scanare folder XML (ID: {TARGET_FOLDER_ID})...")
    
    page_token = None
    # Copiat ID-ul exact de query din scriptul tău vechi de succes
    query = f"'{TARGET_FOLDER_ID}' in parents and trashed = false"
    
    fisiere_marcate = []
    
    while True:
        response = service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name, description)", 
            pageToken=page_token, 
            pageSize=1000,
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True, 
            corpora="user"  # Păstrat fix ca în scriptul tău vechi care mergea
        ).execute()
        
        fișiere = response.get("files", [])
        
        # Filtrare brută în Python, fără bătăi de cap cu API-ul
        for f in fișiere:
            nume = f.get('name', '').lower()
            descriere = f.get('description', '')
            
            if nume.endswith('.xml') and descriere == "processed_for_tags: true":
                fisiere_marcate.append(f)
                
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    if not fisiere_marcate:
        print("✨ Nu s-a găsit niciun XML marcat. Totul este pregătit pentru o căutare fresh!")
        return

    print(f"⚙️ Am găsit {len(fisiere_marcate)} fișiere. Începe curățarea...")
    for idx, xml in enumerate(fisiere_marcate, 1):
        try:
            service.files().update(
                fileId=xml["id"], 
                body={"description": ""}, 
                supportsAllDrives=True
            ).execute()
            
            if idx % 100 == 0 or idx == len(fisiere_marcate):
                print(f"    ✅ [{idx}/{len(fisiere_marcate)}] Resetat: {xml['name']}")
        except Exception as e:
            continue

    print("\n🚀 Resetare completă!")

if __name__ == "__main__":
    reseteaza_atribute_xml()
