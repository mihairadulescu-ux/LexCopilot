# Culori pentru un log frumos în consolă
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

import os
import sys
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_XML")

def obtine_drive():
    print(f"{VERDE}🔑 [Reset XML] Conectare Google Drive...{RESET}")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipsește secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def reseteaza_atribute_xml():
    if not TARGET_FOLDER_ID:
        print(f"{ROSU}🛑 Eroare configurare: DRIVE_FOLDER_XML nu este definit în mediu!{RESET}")
        return

    service = obtine_drive()
    print(f"📂 Scanare folder XML (ID: {TARGET_FOLDER_ID})...")
    
    # 🔍 PASUL CRUCIAL PENTRU SHARED DRIVES: Detectăm ID-ul rădăcină al Shared Drive-ului
    print("🕵️‍♂️ Identificare automată context Shared Drive...")
    try:
        folder_meta = service.files().get(
            fileId=TARGET_FOLDER_ID, 
            fields="driveId", 
            supportsAllDrives=True
        ).execute()
        drive_id = folder_meta.get("driveId")
    except Exception as e:
        print(f"{ROSU}🛑 Eroare la detectarea Shared Drive-ului: {e}{RESET}")
        return

    if not drive_id:
        print(f"{GALBEN}⚠️ Folderul pare să fie în My Drive normal, nu în Shared Drive. Rulăm configurarea standard...{RESET}")

    # Reconstruim argumentele apelului exact conform normelor Shared Drives
    kwargs = {
        "q": f"'{TARGET_FOLDER_ID}' in parents and trashed = false",
        "fields": "nextPageToken, files(id, name, description)",
        "pageSize": 1000,
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True
    }
    
    # Dacă folderul se află pe un Shared Drive, API-ul v3 cere obligatoriu acești parametri
    if drive_id:
        kwargs["corpora"] = "drive"
        kwargs["driveId"] = drive_id

    page_token = None
    fisiere_marcate = []
    contor_total = 0
    
    print("🔍 Citire listă fișiere...")
    while True:
        if page_token:
            kwargs["pageToken"] = page_token
            
        response = service.files().list(**kwargs).execute()
        fișiere = response.get("files", [])
        contor_total += len(fișiere)
        
        for f in fișiere:
            if f['name'].lower().endswith('.xml') and f.get("description") == "processed_for_tags: true":
                fisiere_marcate.append(f)
                
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    print(f"📊 Scanare finalizată. Din totalul de {contor_total} fișiere detectate, {len(fisiere_marcate)} sunt XML-uri deja marcate.")

    if not fisiere_marcate:
        print(f"{VERDE}✨ Nu s-a găsit niciun XML marcat cu etichetă. Totul este pregătit pentru o căutare fresh!{RESET}")
        return

    print(f"⚙️ Se începe curățarea etichetelor...")
    for idx, xml in enumerate(fisiere_marcate, 1):
        f_id = xml["id"]
        f_nume = xml["name"]
        
        try:
            service.files().update(fileId=f_id, body={"description": ""}, supportsAllDrives=True).execute()
            if idx % 100 == 0 or idx == len(fisiere_marcate):
                print(f"    ✅ [{idx}/{len(fisiere_marcate)}] Resetat cu succes: {f_nume}")
        except Exception as e:
            print(f"{ROSU}    ❌ Eroare la resetarea fișierului {f_nume}: {e}{RESET}")
            continue

    print(f"\n{VERDE}🚀 Resetare completă! Marcajele au fost eliminate cu succes din Shared Drive.{RESET}")

if __name__ == "__main__":
    reseteaza_atribute_xml()
