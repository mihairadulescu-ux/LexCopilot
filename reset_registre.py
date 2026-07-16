import os
import sys
import json
import csv
import io
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Destinația pentru folderele de PDF brute
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF", "1gRh-rWe32RNJU2PmN67XoFvkaCSotTA1")

def obtine_drive():
    print("🔑 [Reset] Conectare Google Drive...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_toate_pdf_urile_fizice(service):
    """Scanează folderul o singură dată și extrage fișierele cu metadatele de dimensiune."""
    print(f"📂 Scanare generală folder PDF (ID: {TARGET_FOLDER_ID})...")
    pdf_uri = []
    page_token = None
    
    query = f"'{TARGET_FOLDER_ID}' in parents and mimeType = 'application/pdf' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name, size)", 
            pageToken=page_token, 
            pageSize=1000,
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True, 
            corpora="user"
        ).execute()
        
        pdf_uri.extend(response.get("files", []))
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    print(f"📊 S-au găsit în total {len(pdf_uri)} fișiere PDF fizice în Drive.")
    return pdf_uri

def sparge_numar_si_sufix(nume_fisier):
    """
    Sparge denumirea standardizată în trei componente atomice:
    Exemple:
      - MO_PI_2020_1S.pdf         -> an='2020', nr_baza=1, sufix='S'
      - MO_PI_2004_123.pdf        -> an='2004', nr_baza=123, sufix=''
      - MO_PI_2015_45Bis.pdf      -> an='2015', nr_baza=45, sufix='Bis'
      - MO_PI_2021_14Supliment.pdf-> an='2021', nr_baza=14, sufix='Supliment'
    """
    m = re.search(r"MO_PI_(\d{4})_([A-Za-z0-9]+)\.pdf", nume_fisier)
    if m:
        an = m.group(1)
        numar_complet = m.group(2)
        
        # Izolăm cifrele de la începutul grupului de număr
        match_baza = re.match(r"^(\d+)", numar_complet)
        if match_baza:
            nr_baza = int(match_baza.group(1))
            # Sufixul reprezintă tot ce rămâne după cifrele de bază
            sufix = numar_complet[len(match_baza.group(1)):]
            return an, nr_baza, sufix
            
    return None, None, None

def reseteaza_tot():
    service = obtine_drive()
    
    toate_pdf_urile = listeaza_toate_pdf_urile_fizice(service)
    if not toate_pdf_urile:
        print("⚠️ ATENȚIE: Nu s-a găsit niciun PDF potrivit în folder! Nimic de resetat.")
        return

    # Structura din memorie: { "2020": [ { "nr_baza": 1, "sufix": "S", "id": "...", "size": 12 }, ... ] }
    date_pe_ani = {}
    
    for pdf in toate_pdf_urile:
        nume = pdf["name"]
        an, nr_baza, sufix = sparge_numar_si_sufix(nume)
        
        if an is not None and nr_baza is not None:
            if an not in date_pe_ani:
                date_pe_ani[an] = []
                
            raw_size = pdf.get("size")
            size_kb = round(int(raw_size) / 1024, 1) if raw_size else 0.0
            
            date_pe_ani[an].append({
                "nr_baza": nr_baza,
                "sufix": sufix,
                "size_kb": size_kb,
                "id": pdf["id"]
            })
            
    print(f"🗂️ Fișierele au fost catalogate în memorie pentru {len(date_pe_ani)} ani.")

    # 3. Generare și scriere registre ordonate natural
    for an, rows in sorted(date_pe_ani.items()):
        nume_registru = f"status_{an}.csv"
        print(f"⚙️ Generare registru sortat: {nume_registru} ({len(rows)} PDF-uri)...")
        
        # Sortare multi-criteriu: mai întâi crescător după numărul de bază (numeric), apoi alfabetic după sufix
        rows.sort(key=lambda x: (x["nr_baza"], x["sufix"]))
        
        query_reg = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
        existente = service.files().list(
            q=query_reg, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
        ).execute().get("files", [])
        
        cale_temp = f"temp_{nume_registru}"
        with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Structura nouă a antetului cu coloane separate clar
            writer.writerow(["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
            
            for r in rows:
                writer.writerow([r["nr_baza"], r["sufix"], "descarcat", r["size_kb"], r["id"]])
                
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        if existente:
            file_id = existente[0]["id"]
            service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            print(f"   💾 Sincronizat [UPDATE]: {nume_registru} (ID: {file_id})")
        else:
            metadata = {'name': nume_registru, 'parents': [TARGET_FOLDER_ID]}
            nou = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
            print(f"   🆕 Generat [CREATE]: {nume_registru} (ID: {nou['id']})")
            
        os.remove(cale_temp)
        
    print("🚀 Sincronizarea registrelor de status în ordine naturală s-a terminat cu succes!")

if __name__ == "__main__":
    reseteaza_tot()
