import os
import sys
import json
import re
import csv
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ORIGIN_FOLDER_ID = "1c8SEo8UrQVe6qgzPFGLXJFiMyLeI-r8D"  # Folderul vechi cu de toate
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")        # Noul Shared Drive

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def parseaza_nume_fisier(nume):
    pattern = r"^MO_PI_(?P<an>\d{4})_(?P<numar_complet>\d+[A-Za-z]*?)(?P<failed>_FAILED)?\.pdf$"
    match = re.match(pattern, nume)
    if not match:
        return None
    
    an = int(match.group("an"))
    numar_complet = match.group("numar_complet")
    este_failed = bool(match.group("failed"))
    
    match_numar = re.match(r"^(?P<cifre>\d+)(?P<sufix>[A-Za-z]*)$", numar_complet)
    if not match_numar:
        return None
        
    numar_numeric = int(match_numar.group("cifre"))
    sufix = match_numar.group("sufix").lower()
    
    tip_coloana = "simplu"
    if sufix == "bis":
        tip_coloana = "bis"
    elif sufix == "tris":
        tip_coloana = "tris"
    elif sufix == "quatro":
        tip_coloana = "quatro"
    elif sufix == "s":
        tip_coloana = "s"
    elif sufix != "":
        return None
        
    return {
        "an": an,
        "numar": numar_numeric,
        "tip": tip_coloana,
        "failed": este_failed
    }

def indexeaza_sursa_veche():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE: DRIVE_FOLDER_PDF nu este setat în Variables!")
        sys.exit(1)

    print("🔍 Conectare la Google Drive...")
    service = obtine_drive()
    
    # Inițializăm matricea de stări în memorie pentru toți anii
    print("🧠 Inițializare matrice în memorie (Anii 2000-2026, limită 1500)...")
    stari_ani = {}
    for an in range(2000, 2027):
        stari_ani[an] = {}
        for n in range(1, 1501):
            stari_ani[an][n] = {"simplu": 0, "bis": 0, "tris": 0, "quatro": 0, "s": 0}

    # Scanăm folderul sursă VECHI
    print(f"📂 Scanăm metadatele din folderul sursă vechi ({ORIGIN_FOLDER_ID})...")
    page_token = None
    query = f"'{ORIGIN_FOLDER_ID}' in parents and trashed = false"
    fisiere_scanate = 0
    
    while True:
        # Folosim corpora="user" deoarece scanăm My Drive / folder partajat exterior
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, size)",
            pageToken=page_token,
            pageSize=1000,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="user"
        ).execute()
        
        files = response.get("files", [])
        for f in files:
            nume = f["name"]
            size = int(f.get("size", 0))
            
            if not nume.startswith("MO_PI_") or not nume.endswith(".pdf"):
                continue
                
            info = parseaza_nume_fisier(nume)
            if not info:
                continue
                
            an = info["an"]
            numar = info["numar"]
            tip = info["tip"]
            este_failed = info["failed"]
            
            if an not in stari_ani or numar > 1500:
                continue
                
            fisiere_scanate += 1
            
            # Regulile tale extrem de clare de mapare:
            if size > 1 and not este_failed:
                stari_ani[an][numar][tip] = 20  # DESCĂRCAT CORECT (Materia primă validă)
            else:
                # Fișiere de 1 byte (dummy) sau fișiere _FAILED
                if tip == "simplu":
                    stari_ani[an][numar][tip] = 15  # Eșec critic număr simplu (trebuie recuperat)
                else:
                    stari_ani[an][numar][tip] = 10  # Inexistent confirmat sufix (nu ne mai batem capul)

        page_token = response.get("nextPageToken", None)
        if not page_token:
            break

    print(f"📊 Scanare completă! Am analizat {fisiere_scanate} fișiere brute din sursă.")

    # Generăm CSV-urile local și le urcăm în noul Shared Drive
    print("\n✍️ Generare registre CSV și încărcare direct în noul Shared Drive...")
    director_temp = Path("./temp_registre")
    director_temp.mkdir(exist_ok=True)
    
    for an, date_an in stari_ani.items():
        nume_csv = f"status_{an}.csv"
        cale_csv = director_temp / nume_csv
        
        with open(cale_csv, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["numar", "simplu", "bis", "tris", "quatro", "s"])
            for n in range(1, 1501):
                r = date_an[n]
                writer.writerow([n, r["simplu"], r["bis"], r["tris"], r["quatro"], r["s"]])
                
        # Verificăm dacă există deja în noul Shared Drive ca să-i facem update sau create
        query_csv = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_csv}' and trashed = false"
        existente = service.files().list(
            q=query_csv, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True
        ).execute().get("files", [])
        
        file_id_existent = existente[0]["id"] if existente else None
        media = MediaFileUpload(str(cale_csv), mimetype="text/csv", resumable=True)
        
        if file_id_existent:
            service.files().update(fileId=file_id_existent, media_body=media, supportsAllDrives=True).execute()
            print(f"🔄 Registru actualizat în noul Shared Drive: {nume_csv}", flush=True)
        else:
            metadata = {'name': nume_csv, 'parents': [TARGET_FOLDER_ID]}
            service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
            print(f"🆕 Registru creat în noul Shared Drive: {nume_csv}", flush=True)
            
        cale_csv.unlink()

    print("\n🎉 Toate cele 27 de registre CSV de stare au fost create direct în noul Shared Drive!")

if __name__ == "__main__":
    indexeaza_sursa_veche()
