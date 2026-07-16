import os
import sys
import json
import csv
import io
import time
import random
import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TARGET_FOLDER_ID = "1gRh-rWe32RNJU2PmN67XoFvkaCSotTA1"

AN_CURENT = os.getenv("AN_PROCESAT")
if not AN_CURENT:
    print("❌ EROARE CRITICĂ: Variabila de mediu 'AN_PROCESAT' nu este setată!")
    sys.exit(1)

URL_TEMPLATE = "https://www.monitoruloficial.ro/emonitor/PDF_baza.php?an={an}&numar={numar}"

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def descarca_si_salveaza_simple():
    service = obtine_drive()
    nume_registru = f"status_{AN_CURENT}.csv"
    
    query = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
    existente = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute().get("files", [])
    
    randuri_registru = []
    fisiere_descarcate = set()
    file_id_registru = None

    if existente:
        file_id_registru = existente[0]["id"]
        request = service.files().get_media(fileId=file_id_registru)
        continut_bytes = request.execute()
        
        fh = io.BytesIO(continut_bytes)
        wrapper = io.TextIOWrapper(fh, encoding='utf-8')
        reader = csv.DictReader(wrapper)
        
        for row in reader:
            randuri_registru.append(row)
            if row.get("status") == "descarcat" and not row.get("sufix"):
                randuri_registru_nr = row.get("numar_baza")
                if randuri_registru_nr:
                    fisiere_descarcate.add(int(randuri_registru_nr))
    
    print(f"📊 Anul {AN_CURENT}: {len(fisiere_descarcate)} numere simple detectate deja ca descărcate.")

    # Inițiem o sesiune HTTP persistentă cu headere de browser real
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7"
    })

    consecutive_errors = 0

    for nr in range(1, 1201):
        if nr in fisiere_descarcate:
            continue
            
        nume_pdf = f"MO_PI_{AN_CURENT}_{nr}.pdf"
        url = URL_TEMPLATE.format(an=AN_CURENT, numar=nr)
        
        # Pauză mică și random între cereri ca să nu pară atac automat (1.0 - 2.5 secunde)
        time.sleep(random.uniform(1.0, 2.5))
        
        print(f"⏳ Descarcă {nume_pdf}...")
        try:
            res = session.get(url, timeout=30)
            
            # Resetăm contorul de erori la un răspuns de succes de la server
            consecutive_errors = 0
            
            if res.status_code == 200 and len(res.content) > 2000:
                size_kb = round(len(res.content) / 1024, 1)
                
                cale_pdf_temp = f"temp_{nume_pdf}"
                with open(cale_pdf_temp, "wb") as f_pdf:
                    f_pdf.write(res.content)
                    
                metadata = {'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]}
                media = MediaFileUpload(cale_pdf_temp, mimetype="application/pdf")
                nou_pdf = service.files().create(
                    body=metadata, media_body=media, fields="id", supportsAllDrives=True
                ).execute()
                os.remove(cale_pdf_temp)
                
                randuri_registru.append({
                    "numar_baza": str(nr),
                    "sufix": "",
                    "status": "descarcat",
                    "dimensiune_kb": str(size_kb),
                    "drive_file_id": nou_pdf["id"]
                })
                print(f"   ✓ Succes ({size_kb} KB) -> ID: {nou_pdf['id']}")
            else:
                print(f"   ✗ Numărul {nr} nu e disponibil (Pagina goala/Eroare server).")
        except Exception as e:
            consecutive_errors += 1
            print(f"   ⚠️ Eroare conexiune la numărul {nr}: {e}")
            
            # Siguranță: dacă primim 10 erori consecutive de conexiune, înseamnă că IP-ul e blocat de tot
            if consecutive_errors >= 10:
                print("🚨 BLOCAJ DETECTAT: Prea multe erori de conexiune consecutive. Oprim execuția pentru salvare.")
                break
            
            # Așteptăm mai mult în caz de eroare, dând timp serverului să se liniștească
            time.sleep(10)

    randuri_registru.sort(key=lambda x: (int(x["numar_baza"]), x.get("sufix", "")))
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
    print(f"🚀 Registru {nume_registru} salvat securizat în Drive!")

if __name__ == "__main__":
    descarca_si_salveaza_simple()
