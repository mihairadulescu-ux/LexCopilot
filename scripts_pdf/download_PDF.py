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

URL_TEMPLATE = "https://www.monitoruloficial.ro/emonitor/PDF_baza.php?an={an}&numar={numar}{sufix}"
GREEN, YELLOW, RED, RESET = "\033[92m", "\033[93m", "\033[91m", "\033[0m"

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def obtine_sau_creeaza_registru(service, nume_registru, drive_folder_pdf):
    query = f"'{drive_folder_pdf}' in parents and name = '{nume_registru}' and trashed = false"
    existente = service.files().list(q=query, fields="files(id)", supportsAllDrives=True).execute().get("files", [])
    
    if existente:
        file_id = existente[0]["id"]
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0)
        return file_id, list(csv.DictReader(io.StringIO(fh.read().decode("utf-8"))))
    else:
        cale_temp = f"temp_init_{nume_registru}"
        with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
            writer.writeheader()
        metadata = {'name': nume_registru, 'parents': [drive_folder_pdf]}
        nou = service.files().create(body=metadata, media_body=MediaFileUpload(cale_temp, mimetype="text/csv"), fields="id", supportsAllDrives=True).execute()
        os.remove(cale_temp)
        return nou["id"], []

def salveaza_registru_in_drive(service, file_id, nume_registru, randuri):
    cale_temp = f"temp_save_{nume_registru}"
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
        writer.writeheader()
        writer.writerows(randuri)
    service.files().update(fileId=file_id, media_body=MediaFileUpload(cale_temp, mimetype="text/csv"), supportsAllDrives=True).execute()
    os.remove(cale_temp)
    return file_id

def incarca_pdf_in_drive(service, cale_local_pdf, nume_pdf, drive_folder_pdf):
    metadata = {'name': nume_pdf, 'parents': [drive_folder_pdf]}
    media = MediaFileUpload(cale_local_pdf, mimetype="application/pdf", resumable=True)
    return service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute().get("id")

def executa_sincronizare_totala():
    AN_CURENT = os.getenv("AN_CURENT")
    DRIVE_FOLDER_PDF = os.getenv("DRIVE_FOLDER_PDF")

    if not AN_CURENT or not DRIVE_FOLDER_PDF:
        print(f"{RED}❌ EROARE CRITICĂ: Variabilele de mediu sunt incomplete!{RESET}")
        sys.exit(1)
        
    print(f"🌍 {GREEN}Pornire pipeline UNIFICAT pentru anul {AN_CURENT}...{RESET}")
    service = obtine_drive()
    nume_registru = f"status_{AN_CURENT}.csv"
    file_id_registru, randuri_registru = obtine_sau_creeaza_registru(service, nume_registru, DRIVE_FOLDER_PDF)
    
    fisiere_rezolvate = {(int(r["numar_baza"]), r["sufix"]) for r in randuri_registru if r["status"] in ["descarcat", "inexistent"]}
    
    download_counter, consecutive_errors = 0, 0  
    VARIANTE_DE_VERIFICAT = ["", "Bis", "Tris", "Quater", "S"]
    
    with httpx.Client(limits=httpx.Limits(max_keepalive_connections=5, max_connections=10), timeout=httpx.Timeout(30.0, connect=15.0), follow_redirects=True) as client:
        for nr in range(1, 1201):
            if AN_CURENT == "2026" and consecutive_errors >= 7: break
            if AN_CURENT != "2026" and consecutive_errors >= 100: break
            
            nr_baza_eșuat = False
            
            for sufix in VARIANTE_DE_VERIFICAT:
                if (nr, sufix) in fisiere_rezolvate: continue
                    
                nume_pdf = f"MO_PI_{AN_CURENT}_{nr}{sufix}.pdf"
                url = URL_TEMPLATE.format(an=AN_CURENT, numar=nr, sufix=sufix)
                cale_pdf_temp = f"temp_{nume_pdf}"
                
                print(f"⏳ Verificare: {nume_pdf}...")
                descarcat_ok, lovit_503, lovit_404 = False, False, False
                
                try:
                    response = client.get(url)
                    if response.status_code == 200 and "application/pdf" in response.headers.get("content-type", "").lower():
                        with open(cale_pdf_temp, "wb") as f_pdf: f_pdf.write(response.content)
                        descarcat_ok = True
                    elif response.status_code == 404:
                        print(f"   {YELLOW}⚠ Fișier inexistent pe server (404) la {nume_pdf}.{RESET}")
                        lovit_404 = True
                    elif response.status_code == 503:
                        print(f"   {RED}✗ Server ocupat (503) la {nume_pdf}.{RESET}")
                        lovit_503 = True
                except Exception as e:
                    print(f"   ⚠️ Conexiune picată la {nume_pdf}: {e}")
                    time.sleep(3)
                    
                # CAZ 1: GĂSIT ȘI VALID
                if descarcat_ok and os.path.exists(cale_pdf_temp) and os.path.getsize(cale_pdf_temp) > 2000:
                    dimensiune_kb = f"{os.path.getsize(cale_pdf_temp) / 1024:.1f}"
                    try:
                        drive_id = incarca_pdf_in_drive(service, cale_pdf_temp, nume_pdf, DRIVE_FOLDER_PDF)
                        print(f"   {GREEN}✓ Salvat în Drive -> ID: {drive_id}{RESET}")
                        
                        gasit = False
                        for idx, r in enumerate(randuri_registru):
                            if int(r["numar_baza"]) == nr and r["sufix"] == sufix:
                                randuri_registru[idx] = {"numar_baza": str(nr), "sufix": sufix, "status": "descarcat", "dimensiune_kb": dimensiune_kb, "drive_file_id": drive_id}
                                gasit = True
                                break
                        if not gasit:
                            randuri_registru.append({"numar_baza": str(nr), "sufix": sufix, "status": "descarcat", "dimensiune_kb": dimensiune_kb, "drive_file_id": drive_id})
                        
                        if sufix == "": consecutive_errors = 0
                        download_counter += 1
                    except Exception as e: print(f"   ⚠️ Eșec Drive: {e}")
                    finally:
                        if os.path.exists(cale_pdf_temp): os.remove(cale_pdf_temp)
                
                # CAZ 2: SIGUR NU EXISTĂ (404)
                elif lovit_404 or (descarcat_ok and os.path.exists(cale_pdf_temp) and os.path.getsize(cale_pdf_temp) <= 2000):
                    if os.path.exists(cale_pdf_temp): os.remove(cale_pdf_temp)
                    
                    gasit = False
                    for idx, r in enumerate(randuri_registru):
                        if int(r["numar_baza"]) == nr and r["sufix"] == sufix:
                            randuri_registru[idx] = {"numar_baza": str(nr), "sufix": sufix, "status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""}
                            gasit = True
                            break
                    if not gasit:
                        randuri_registru.append({"numar_baza": str(nr), "sufix": sufix, "status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})
                    
                    # Dacă numărul simplu nu există, nu căutăm sufixe
                    if sufix == "": 
                        nr_baza_eșuat = True
                        break 
                
                # CAZ 3: EROARE TEMPORARĂ (503, EROARE REȚEA)
                else:
                    if os.path.exists(cale_pdf_temp): os.remove(cale_pdf_temp)
                    if sufix == "": 
                        nr_baza_eșuat = True
                        # OPTIMIZARE: Dacă numărul simplu e blocat/503, oprim verificarea sufixelor pentru acest număr
                        break
                
                file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                
                if lovit_503: time.sleep(5.0)
                else: time.sleep(1.3)
            
            if nr_baza_eșuat:
                consecutive_errors += 1
                
            if download_counter > 0 and download_counter % 200 == 0:
                print(f"\n☕ Pauză Anti-WAF 5 minute..."); time.sleep(300); download_counter = 0

    print(f"🏁 Pipeline general finalizat pentru anul {AN_CURENT}.")

if __name__ == "__main__":
    executa_sincronizare_totala()
