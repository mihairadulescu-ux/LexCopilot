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

def obtine_sau_creeaza_registru(service, nume_registru, drive_folder_pdf):
    query = f"'{drive_folder_pdf}' in parents and name = '{nume_registru}' and trashed = false"
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
        
        metadata = {'name': nume_registru, 'parents': [drive_folder_pdf]}
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        nou = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
        os.remove(cale_temp)
        print(f"🆕 [{GREEN}CREAT{RESET}] Registru CSV nou (ID: {nou['id']})")
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

def executa_sincronizare_sufixe():
    # CORECTURĂ: Citim direct cu numele exact al variabilelor din mediu
    AN_CURENT = os.getenv("AN_CURENT")
    DRIVE_FOLDER_PDF = os.getenv("DRIVE_FOLDER_PDF")

    if not AN_CURENT or not DRIVE_FOLDER_PDF:
        print(f"{RED}❌ EROARE CRITICĂ: Variabilele de mediu sunt incomplete pentru sufixe!{RESET}")
        print(f"-> AN_CURENT: '{AN_CURENT}', DRIVE_FOLDER_PDF: '{DRIVE_FOLDER_PDF}'")
        sys.exit(1)
        
    print(f"🌍 {GREEN}Inițializare pipeline SUFIXE pentru anul {AN_CURENT}...{RESET}")
    service = obtine_drive()
    
    nume_registru = f"status_{AN_CURENT}.csv"
    file_id_registru, randuri_registru = obtine_sau_creeaza_registru(service, nume_registru, DRIVE_FOLDER_PDF)
    
    fisiere_sufixe_descarcate = set()
    for r in randuri_registru:
        if r["status"] == "descarcat" and r["sufix"] != "":
            fisiere_sufixe_descarcate.add((int(r["numar_baza"]), r["sufix"]))
            
    print(f"📊 Anul {AN_CURENT}: {len(fisiere_sufixe_descarcate)} ediții cu sufix deja validate în Drive.")
    
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(30.0, connect=15.0)
    
    download_counter = 0
    SUFIXE_DE_VERIFICAT = ["Bis", "Tris", "Quater", "S"]
    
    with httpx.Client(limits=limits, timeout=timeout, follow_redirects=True) as client:
        # PLAFONARE MAXIMĂ: Nu depășim limita de 1200 de monitoare simple pentru verificarea sufixelor
        for nr in range(1, 1201):
            
            for sufix in SUFIXE_DE_VERIFICAT:
                if (nr, sufix) in fisiere_sufixe_descarcate:
                    continue
                    
                nume_pdf = f"MO_PI_{AN_CURENT}_{nr}{sufix}.pdf"
                url = URL_TEMPLATE.format(an=AN_CURENT, numar=nr, sufix=sufix)
                cale_pdf_temp = f"temp_{nume_pdf}"
                
                print(f"⏳ Caută variantă specială: {nume_pdf}...")
                descarcat_ok = False
                lovit_503 = False
                
                try:
                    response = client.get(url)
                    if response.status_code == 200:
                        content_type = response.headers.get("content-type", "").lower()
                        if "application/pdf" in content_type:
                            with open(cale_pdf_temp, "wb") as f_pdf:
                                f_pdf.write(response.content)
                            descarcat_ok = True
                    elif response.status_code == 503:
                        print(f"   {RED}✗ Serverul a dat 503 Service Unavailable pentru {nume_pdf}.{RESET}")
                        lovit_503 = True
                except Exception as e:
                    print(f"   ⚠️ Problemă rețea la {nume_pdf}: {e}")
                    time.sleep(3)
                    
                if descarcat_ok and os.path.exists(cale_pdf_temp) and os.path.getsize(cale_pdf_temp) > 2000:
                    dimensiune_bytes = os.path.getsize(cale_pdf_temp)
                    dimensiune_kb = f"{dimensiune_bytes / 1024:.1f}"
                    
                    try:
                        drive_id = incarca_pdf_in_drive(service, cale_local_pdf=cale_pdf_temp, nume_pdf=nume_pdf, drive_folder_pdf=DRIVE_FOLDER_PDF)
                        print(f"   {GREEN}✓ Succes Special ({dimensiune_kb} KB) -> ID: {drive_id}{RESET}")
                        
                        gasit_in_csv = False
                        for idx, r in enumerate(randuri_registru):
                            if int(r["numar_baza"]) == nr and r["sufix"] == sufix:
                                randuri_registru[idx] = {
                                    "numar_baza": str(nr), "sufix": sufix, "status": "descarcat",
                                    "dimensiune_kb": dimensiune_kb, "drive_file_id": drive_id
                                }
                                gasit_in_csv = True
                                break
                                
                        if not gasit_in_csv:
                            randuri_registru.append({
                                "numar_baza": str(nr), "sufix": sufix, "status": "descarcat",
                                "dimensiune_kb": dimensiune_kb, "drive_file_id": drive_id
                            })
                            
                        file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                        download_counter += 1
                        
                    except Exception as e:
                        print(f"   {RED}⚠️ Eroare salvare în Drive: {e}{RESET}")
                    finally:
                        if os.path.exists(cale_pdf_temp):
                            os.remove(cale_pdf_temp)
                else:
                    if os.path.exists(cale_pdf_temp):
                        os.remove(cale_pdf_temp)
                
                # PROTECȚIE DINAMICĂ 503: Dacă serverul obosește la sufixe, punem frână de 5 secunde
                if lovit_503:
                    print(f"   💤 {YELLOW}[Protecție sufixe 503]{RESET} Scurt respiro de 5 secunde pentru server...")
                    time.sleep(5.0)
                else:
                    time.sleep(1.2)
                
            if download_counter > 0 and download_counter % 150 == 0:
                print(f"\n☕ [Pauză sufixe] Am descărcat {download_counter} fișiere speciale. Pauză de 5 minute...")
                time.sleep(300)
                download_counter = 0

    print(f"\n🏁 Sincronizarea edițiilor cu sufix pentru anul {AN_CURENT} s-a încheiat curat.")

if __name__ == "__main__":
    executa_sincronizare_sufixe()
