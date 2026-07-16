import os
import sys
import json
import csv
import io
import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ID-ul fix al folderului tău Google Drive
TARGET_FOLDER_ID = "1gRh-rWe32RNJU2PmN67XoFvkaCSotTA1"

AN_CURENT = os.getenv("AN_PROCESAT")
if not AN_CURENT:
    print("❌ EROARE CRITICĂ: Variabila de mediu 'AN_PROCESAT' nu este setată!")
    sys.exit(1)

URL_TEMPLATE = "https://www.monitoruloficial.ro/emonitor/PDF_baza.php?an={an}&numar={numar}"
SUFIXE_TEST = ["S", "Bis", "Supliment", "A", "B"]

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def descarca_si_salveaza_sufixe():
    service = obtine_drive()
    nume_registru = f"status_{AN_CURENT}.csv"
    
    # 1. Căutăm registrul existent în Drive
    query = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
    existente = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute().get("files", [])
    
    randuri_registru = []
    combinatii_descarcate = set()
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
            if row.get("status") == "descarcat":
                nr_baza = row.get("numar_baza")
                sfx = row.get("sufix", "")
                if nr_baza:
                    combinatii_descarcate.add((int(nr_baza), sfx))
    
    print(f"📊 Anul {AN_CURENT}: {len(combinatii_descarcate)} combinații totale identificate în registru.")

    # 2. Scanăm plaja de numere pentru sufixe speciale
    for nr in range(1, 1201):
        for sfx in SUFIXE_TEST:
            if (nr, sfx) in combinatii_descarcate:
                continue
                
            numar_url = f"{nr}{sfx}"
            nume_pdf = f"MO_PI_{AN_CURENT}_{nr}{sfx}.pdf"
            url = URL_TEMPLATE.format(an=AN_CURENT, numar=numar_url)
            
            try:
                res = requests.get(url, timeout=20)
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
                        "sufix": sfx,
                        "status": "descarcat",
                        "dimensiune_kb": str(size_kb),
                        "drive_file_id": nou_pdf["id"]
                    })
                    print(f"🔥 [SUFIX] Găsit și descărcat: {nume_pdf} ({size_kb} KB)!")
            except Exception as e:
                print(f"   ⚠️ Eroare la verificarea numărului {nr}{sfx}: {e}")

    # 3. Salvăm înapoi registrul ordonat impecabil
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
    print(f"🚀 Registru {nume_registru} actualizat cu noile sufixe în Drive!")

if __name__ == "__main__":
    descarca_si_salveaza_sufixe()
