import os
import sys
import json
import csv
import io
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Pilonul de siguranță - ID-ul folderului tău de PDF-uri
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF", "1gRh-rWe32RNJU2PmN67XoFvkaCSotTA1")

def obtine_drive():
    print("🔑 [Reset] Conectare Google Drive...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_toate_pdf_urile_fizice(service):
    """Scanează folderul o singură dată și aduce ABSOLUT toate fișierele PDF."""
    print(f"📂 Scanare generală folder PDF (ID: {TARGET_FOLDER_ID})...")
    pdf_uri = []
    page_token = None
    
    query = f"'{TARGET_FOLDER_ID}' in parents and mimeType = 'application/pdf' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name)", 
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

def extrage_an_si_numar_din_nume(nume_fisier):
    """
    Extrage anul și numărul alfanumeric din denumirea standardizată.
    Exemple potrivite: 
      - MO_PI_2020_1S.pdf   -> an='2020', numar='1S'
      - MO_PI_2004_123.pdf  -> an='2004', numar='123'
      - MO_PI_2015_45Bis.pdf -> an='2015', numar='45Bis'
    """
    # Regex-ul caută prefixul fix MO_PI_, urmat de 4 cifre (anul), un underscore și numărul complet de dinainte de .pdf
    m = re.search(r"MO_PI_(\d{4})_([A-Za-z0-9]+)\.pdf", nume_fisier)
    if m:
        return m.group(1), m.group(2)
    return None, None

def sorteaza_numere_inteligent(item):
    """Functie helper pentru a sorta numerele alfanumerice cat mai natural."""
    numar_str = item[0]
    # Extragem doar cifrele de la inceput pentru sortare numerica primara
    cifre = re.match(r"^\d+", numar_str)
    return int(cifre.group(0)) if cifre else 999999

def reseteaza_tot():
    service = obtine_drive()
    
    # 1. Luăm lista completă de pe Drive o singură dată
    toate_pdf_urile = listeaza_toate_pdf_urile_fizice(service)
    
    if not toate_pdf_urile:
        print("⚠️ ATENȚIE: Nu s-a găsit niciun PDF potrivit în folder! Nimic de resetat.")
        return

    # 2. Mapăm fișierele pe ani în memorie
    pdf_pe_ani = {} 
    
    for pdf in toate_pdf_urile:
        nume = pdf["name"]
        an, numar = extrage_an_si_numar_din_nume(nume)
        if an and numar:
            if an not in pdf_pe_ani:
                pdf_pe_ani[an] = {}
            pdf_pe_ani[an][numar] = pdf["id"]
            
    print(f"🗂️ Fișierele au fost catalogate în memorie pentru {len(pdf_pe_ani)} ani diferiți.")

    # 3. Actualizăm registrele de status doar pentru anii identificați în Drive
    for an, pdf_dict in sorted(pdf_pe_ani.items()):
        nume_registru = f"status_{an}.csv"
        print(f"⚙️ Sincronizare registru: {nume_registru} ({len(pdf_dict)} PDF-uri)...")
        
        # Căutăm dacă există deja registrul de status în Drive
        query_reg = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
        existente = service.files().list(
            q=query_reg, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
        ).execute().get("files", [])
        
        cale_temp = f"temp_{nume_registru}"
        with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["numar", "status", "drive_file_id"])
            
            # Sortăm alfanumeric listele (ex: 1, 1S, 2, 3)
            for numar, file_id in sorted(pdf_dict.items(), key=sorteaza_numere_inteligent):
                writer.writerow([numar, "descarcat", file_id])
                
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        if existente:
            file_id = existente[0]["id"]
            service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            print(f"   💾 Actualizat registru existent: {nume_registru} (ID: {file_id})")
        else:
            metadata = {'name': nume_registru, 'parents': [TARGET_FOLDER_ID]}
            nou = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
            print(f"   🆕 Creat registru nou: {nume_registru} (ID: {nou['id']})")
            
        os.remove(cale_temp)
        
    print("🚀 Sincronizarea registrelor de status s-a terminat cu succes!")

if __name__ == "__main__":
    reseteaza_tot()
