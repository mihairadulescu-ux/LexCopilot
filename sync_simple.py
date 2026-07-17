import os
import sys
import json
import csv
import io
import time
import httpx
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

URL_TEMPLATE = "https://www.monitoruloficial.ro/emonitor/PDF_baza.php?an={an}&numar={numar}"

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipsește secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def obtine_sau_creeaza_registru(service, nume_registru, metadata_folder_id):
    query = f"'{metadata_folder_id}' in parents and name = '{nume_registru}' and trashed = false"
    existente = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
    ).execute().get("files", [])
    
    fieldnames = ["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"]
    
    if existente:
        file_id = existente[0]["id"]
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        fh.seek(0)
        reader = csv.DictReader(io.StringIO(fh.read().decode("utf-8")))
        return file_id, list(reader)
    else:
        cale_temp = f"temp_init_{nume_registru}"
        with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        
        metadata = {'name': nume_registru, 'parents': [metadata_folder_id]}
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        nou = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
        os.remove(cale_temp)
        print(f"🆕 [{GREEN}CREAT{RESET}] Registru CSV nou în folderul de metadate (ID: {nou['id']})")
        return nou["id"], []

def salveaza_registru_in_drive(service, file_id, nume_registru, randuri):
    cale_temp = f"temp_save_{nume_registru}"
    fieldnames = ["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"]
    
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(randuri)
        
    media = MediaFileUpload(cale_temp, mimetype="text/csv", resumable=False)
    service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
    os.remove(cale_temp)
    return file_id

def incarca_pdf_in_drive(service, cale_local_pdf, nume_pdf, drive_folder_pdf):
    metadata = {'name': nume_pdf, 'parents': [drive_folder_pdf]}
    media = MediaFileUpload(cale_local_pdf, mimetype="application/pdf", resumable=True)
    fisier_drive = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
    return fisier_drive.get("id")

def executa_sincronizare():
    # Preluare dinamică a variabilelor de mediu direct în firul de execuție principal al funcției
    an_curent = os.getenv("AN_CURENT")
    drive_folder_pdf = os.getenv("DRIVE_FOLDER_PDF")
    metadata_folder_id = os.getenv("METADATA_FOLDER_ID")

    if not an_curent or not drive_folder_pdf or not metadata_folder_id:
        print(f"{RED}❌ EROARE CRITICĂ: Variabilele de mediu sunt incomplete!{RESET}")
        print(f"-> AN_CURENT: '{an_curent}', DRIVE_FOLDER_PDF: '{drive_folder_pdf}', METADATA_FOLDER_ID: '{metadata_folder_id}'")
        sys.exit(1)
        
    print(f"🌍 {GREEN}Inițializare pipeline legislativ pentru anul {an_curent}...{RESET}")
    service = obtine_drive()
    
    nume_registru = f"status_{an_curent}.csv"
    file_id_registru, randuri_registru = obtine_sau_creeaza_registru(service, nume_registru, metadata_folder_id)
    
    # Colectăm doar tuplurile (numar, sufix) complet descărcate
    fisiere_simple_descarcate = set()
    for r in randuri_registru:
        if r["status"] == "descarcat" and r["sufix"] == "":
            fisiere_simple_descarcate.add(int(r["numar_baza"]))
            
    print(f"📊 Anul {an_curent}: {len(fisiere_simple_descarcate)} numere simple validate deja în Drive.")
    
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(30.0, connect=15.0)
    
    download_counter = 0
    consecutive_errors = 0  
    
    with httpx.Client(limits=limits, timeout=timeout, follow_redirects=True) as client:
        for nr in range(1, 1201):
            
            # --- 1. FRÂNĂ INTELIGENTĂ AN CURENT (2026) ---
            if an_curent == "2026" and consecutive_errors >= 7:
                print(f"\n🛑 {YELLOW}[FRÂNĂ 2026]{RESET} S-au detectat {consecutive_errors} goluri consecutive. Am ajuns la zi cu anul 2026. Oprire.")
                break
                
            # --- 2. FRÂNĂ INTELIGENTĂ ANI ISTORICI ---
            if an_curent != "2026" and consecutive_errors >= 100:
                print(f"\n🛑 {YELLOW}[FINAL DE AN ISTORIC]{RESET} Am detectat {consecutive_errors} goluri consecutive în anul {an_curent}. Sigur s-a terminat anul. Oprire sprint.")
                break
                
            if nr in fisiere_simple_descarcate:
                continue
                
            nume_pdf = f"MO_PI_{an_curent}_{nr}.pdf"
            url = URL_TEMPLATE.format(an=an_curent, numar=nr)
            cale_pdf_temp = f"temp_{nume_pdf}"
            
            print(f"⏳ Descarcă {nume_pdf}...")
            descarcat_ok = False
            
            try:
                response = client.get(url)
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "").lower()
                    
                    if "application/pdf" in content_type:
                        with open(cale_pdf_temp, "wb") as f_pdf:
                            f_pdf.write(response.content)
                        descarcat_ok = True
                    else:
                        print(f"   ✗ Endpoint-ul a întors HTML în loc de PDF la numărul {nr}.")
                else:
                    print(f"   ✗ Serverul a returnat status code: {response.status_code} pentru numărul {nr}.")
                    
            except Exception as e:
                print(f"   {RED}⚠️ Eroare de rețea la numărul {nr}: {e}{RESET}")
                time.sleep(2)
                
            # --- LOGICĂ DE SALVARE ȘI SINCRONIZARE ---
            if descarcat_ok and os.path.exists(cale_pdf_temp) and os.path.getsize(cale_pdf_temp) > 2000:
                dimensiune_bytes = os.path.getsize(cale_pdf_temp)
                dimensiune_kb = f"{dimensiune_bytes / 1024:.1f}"
                
                try:
                    drive_id = incarca_pdf_in_drive(service, cale_local_pdf=cale_pdf_temp, nume_pdf=nume_pdf, drive_folder_pdf=drive_folder_pdf)
                    print(f"   {GREEN}✓ Succes ({dimensiune_kb} KB) -> ID: {drive_id}{RESET}")
                    
                    gasit_in_csv = False
                    for idx, r in enumerate(randuri_registru):
                        if int(r["numar_baza"]) == nr and r["sufix"] == "":
                            randuri_registru[idx] = {
                                "numar_baza": str(nr),
                                "sufix": "",
                                "status": "descarcat",
                                "dimensiune_kb": dimensiune_kb,
                                "drive_file_id": drive_id
                            }
                            gasit_in_csv = True
                            break
                    
                    if not gasit_in_csv:
                        randuri_registru.append({
                            "numar_baza": str(nr),
                            "sufix": "",
                            "status": "descarcat",
                            "dimensiune_kb": dimensiune_kb,
                            "drive_file_id": drive_id
                        })
                    
                    file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                    consecutive_errors = 0  
                    download_counter += 1
                    
                except Exception as e:
                    print(f"   {RED}⚠️ Eroare la încărcarea în Drive pentru numărul {nr}: {e}{RESET}")
                finally:
                    if os.path.exists(cale_pdf_temp):
                        os.remove(cale_pdf_temp)
            else:
                if os.path.exists(cale_pdf_temp):
                    os.remove(cale_pdf_temp)
                
                consecutive_errors += 1
                
                if an_curent == "2026":
                    print(f"   ⚠️ Numărul {nr} (2026) nu este încă publicat în realitate. Trecem peste.")
                else:
                    print(f"   ⚠️ Numărul {nr} (istoric) nu există. Trecem peste.")
            
            time.sleep(0.5)
            
            if download_counter > 0 and download_counter % 200 == 0:
                print(f"\n☕ {YELLOW}[Pauză de protecție IP]{RESET} Am descărcat {download_counter} fișiere. Pauză de 5 minute (300s)...")
                time.sleep(300)
                download_counter = 0

    print(f"\n🏁 {GREEN}Procesul de sincronizare pentru anul {an_curent} s-a finalizat elegant și curat.{RESET}")

if __name__ == "__main__":
    executa_sincronizare()
