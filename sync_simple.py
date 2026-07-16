import os
import sys
import json
import csv
import io
import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")
AN_CURENT = os.getenv("AN_PROCESAT", "2026")
URL_TEMPLATE = "https://www.monitoruloficial.ro/emonitor/PDF_baza.php?an={an}&numar={numar}"

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def descarca_si_salveaza_simple():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE: DRIVE_FOLDER_PDF nu este setat!")
        sys.exit(1)

    service = obtine_drive()
    nume_registru = f"status_{AN_CURENT}.csv"
    
    # 1. Căutăm registrul existent în Drive
    query = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
    existente = service.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
    
    randuri_registru = []
    fisiere_descarcate = set()
    file_id_registru = None

    if existente:
        file_id_registru = existente[0]["id"]
        request = service.files().get_media(fileId=file_id_registru)
        fh = io.BytesIO()
        downloader = io.FileIO(cale_temp := f"temp_citire_{nume_registru}", "wb")
        
        # Descarcă registrul pentru citire
        request = service.files().get_media(fileId=file_id_registru)
        request.execute() # Pentru simplitate în GitHub Actions descarcă direct fluxul bytes
        
        with open(cale_temp, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                randuri_registru.append(row)
                # Dacă are status descarcat și NU are sufix, îl marcăm ca procesat
                if row["status"] == "descarcat" and not row["sufix"]:
                    fisiere_descarcate.add(int(row["numar_baza"]))
        os.remove(cale_temp)
    
    print(f"📊 Anul {AN_CURENT}: {len(fisiere_descarcate)} numere simple detectate deja ca descărcate.")

    # 2. Definim plaja de lucru (Exemplu: numere de la 1 la 1200)
    for nr in range(1, 1201):
        if nr in fisiere_descarcate:
            continue
            
        nume_pdf = f"MO_PI_{AN_CURENT}_{nr}.pdf"
        url = URL_TEMPLATE.format(an=AN_CURENT, numar=nr)
        
        print(f"⏳ Descarcă {nume_pdf}...")
        res = requests.get(url, timeout=30)
        
        if res.status_code == 200 and len(res.content) > 2000: # Ignorăm paginile de eroare mici (sub 2KB)
            size_kb = round(len(res.content) / 1024, 1)
            
            # Încărcare directă în Google Drive
            cale_pdf_temp = f"temp_{nume_pdf}"
            with open(cale_pdf_temp, "wb") as f_pdf:
                f_pdf.write(res.content)
                
            metadata = {'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]}
            media = MediaFileUpload(cale_pdf_temp, mimetype="application/pdf")
            nou_pdf = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
            os.remove(cale_pdf_temp)
            
            # Adăugăm în structura de registru noua linie
            randuri_registru.append({
                "numar_baza": str(nr),
                "sufix": "",
                "status": "descarcat",
                "dimensiune_kb": str(size_kb),
                "drive_file_id": nou_pdf["id"]
            })
            print(f"   ✓ Succes ({size_kb} KB) -> ID: {nou_pdf['id']}")
        else:
            print(f"   ✗ Numărul {nr} nu e disponibil sau e invalid.")

    # 3. Rescriem și urcăm înapoi registrul actualizat și sortat natural
    randuri_registru.sort(key=lambda x: (int(x["numar_baza"]), x["sufix"]))
    cale_reg_scrie = f"temp_scrie_{nume_registru}"
    
    with open(cale_reg_scrie, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
        writer.writeheader()
        writer.writerows(randuri_registru)
        
    media_reg = MediaFileUpload(cale_reg_scrie, mimetype="text/csv")
    if file_id_registru:
        service.files().update(fileId=file_id_registru, media_body=media_reg, supportsAllDrives=True).execute()
    else:
        metadata = {'name': nume_registru, 'parents': [TARGET_FOLDER_ID]}
        service.files().create(body=metadata, media_body=media_reg, supportsAllDrives=True).execute()
        
    os.remove(cale_reg_scrie)
    print(f"🚀 Registru {nume_registru} actualizat la zi în Drive!")

if __name__ == "__main__":
    descarca_si_salveaza_simple()
