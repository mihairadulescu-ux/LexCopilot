import os
import sys
import time
import random
from pathlib import Path
import httpx
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ======================================================================
# CONFIGURARE GOOGLE DRIVE (FOLDER NOU PDF - COMPATIBILITATE MAXIMĂ)
# ======================================================================
GOOGLE_DRIVE_FOLDER_ID = "1c8SEo8UrQVe6qgzPFGLXJFiMyLeI-r8D"

def instantiaza_drive():
    """Inițializează conexiunea securizată cu Google Drive API folosind Secretul existent."""
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON din mediul de rulare!")
    
    import json
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds)

def adu_fisiere_existente_in_drive(drive_service, folder_id):
    """Scanează cloud-ul folosind setările de compatibilitate extinsă."""
    existente = set()
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    
    while True:
        response = drive_service.files().list(
            q=query, 
            fields="nextPageToken, files(name)", 
            pageToken=page_token, 
            pageSize=1000,
            # Forțează motorul Google să caute folderul în toate locațiile accesibile de robot:
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        for f in response.get("files", []):
            existente.add(f["name"])
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
    return existente

def incarca_in_drive(drive_service, cale_locala, folder_id):
    """Încarcă PDF-ul în Drive cu permisiuni forțate și îl șterge local după succes."""
    nume_fisier = cale_locala.name
    metadata = {'name': nume_fisier, 'parents': [folder_id]}
    media = MediaFileUpload(str(cale_locala), mimetype='application/pdf', resumable=True)
    
    try:
        file_drive = drive_service.files().create(
            body=metadata, 
            media_body=media, 
            fields='id',
            # Forțează upload-ul chiar dacă folderul este într-un Shared Drive sau are reguli stricte:
            supportsAllDrives=True
        ).execute()
        if file_drive.get('id'):
            cale_locala.unlink() # Ștergere locală după succes
            return True
    except Exception as e:
        print(f"❌ [Drive Err] Nu s-a putut încărca {nume_fisier}: {e}", flush=True)
    return False

# ======================================================================
# CORE CRAWLER PDF MONITORUL OFICIAL
# ======================================================================
def descarca_monitoare_pdf(an_start=2000, an_stop=2026):
    url_template = "https://monitoruloficial.ro/Monitorul-Oficial--PI--{numar}--{an}.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://monitoruloficial.ro/e-monitor/"
    }
    
    print("🔄 Conectare la Google Drive și preluare index...", flush=True)
    try:
        drive_service = instantiaza_drive()
        fisiere_drive = adu_fisiere_existente_in_drive(drive_service, GOOGLE_DRIVE_FOLDER_ID)
        print(f"📊 Detectate {len(fisiere_drive)} PDF-uri salvate deja în cloud.", flush=True)
    except Exception as e:
        print(f"🛑 Eroare critică la inițializarea Google Drive: {e}", flush=True)
        return

    # Folder temporar pe mașina GitHub Actions
    director_temp = Path("./temp_pdf_download")
    director_temp.mkdir(exist_ok=True)
    
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        for an in range(an_start, an_stop + 1):
            print(f"\n=================== PROCESĂM ANUL {an} ===================", flush=True)
            
            numar_curent = 1
            erori_consecutive = 0
            limita_erori = 50 # 10 numere consecutive lipsă = an terminat
            
            while True:
                variante_numar = [
                    str(numar_curent), 
                    f"{numar_curent}Bis", 
                    f"{numar_curent}Tris",
                    f"{numar_curent}Quater",
                    f"{numar_curent}S"
                ]
                document_gasit_pe_server = False
                
                for varianta in variante_numar:
                    nume_fisier = f"MO_PI_{an}_{varianta}.pdf"
                    cale_finala_locala = director_temp / nume_fisier
                    cale_temporara = director_temp / f"{nume_fisier}.part"
                    
                    # Sari peste dacă e deja în Drive
                    if nume_fisier in fisiere_drive:
                        print(f"☁️ [Există în Drive] {nume_fisier}", flush=True)
                        document_gasit_pe_server = True
                        if varianta == str(numar_curent):
                            erori_consecutive = 0
                        continue
                    
                    url = url_template.format(numar=varianta, an=an)
                    
                    try:
                        with client.stream("GET", url) as response:
                            if response.status_code == 404:
                                continue
                            
                            if response.status_code in [500, 502, 503, 504]:
                                print(f"⚠️ [Server Error {response.status_code}] La {varianta}/{an}. Se va reîncerca ulterior.", flush=True)
                                document_gasit_pe_server = True 
                                continue
                                
                            response.raise_for_status()
                            
                            tip_continut = response.headers.get("Content-Type", "")
                            if "application/pdf" not in tip_continut:
                                continue
                            
                            if varianta == str(numar_curent):
                                erori_consecutive = 0
                            document_gasit_pe_server = True
                            
                            # Descărcare atomică
                            with open(cale_temporara, "wb") as f_temp:
                                for chunk in response.iter_bytes(chunk_size=65536):
                                    f_temp.write(chunk)
                            
                            cale_temporara.replace(cale_finala_locala)
                            print(f"📥 Descărcat local: {nume_fisier}", flush=True)
                            
                            # Sincronizare Cloud
                            if incarca_in_drive(drive_service, cale_finala_locala, GOOGLE_DRIVE_FOLDER_ID):
                                print(f"✅ [Sincronizat Drive] {nume_fisier}", flush=True)
                            
                            # Pauza politicoasă
                            time.sleep(random.uniform(5.0, 8.0))
                            
                    except Exception as e:
                        print(f"❌ [Eroare] Număr {varianta}/{an}: {e}", flush=True)
                        if cale_temporara.exists():
                            cale_temporara.unlink()
                        time.sleep(6.0)
                
                if not document_gasit_pe_server:
                    erori_consecutive += 1
                
                if erori_consecutive >= limita_erori:
                    print(f"🏁 [Sfârșit de an] Anul {an} s-a încheiat după {limita_erori} încercări goale.", flush=True)
                    break
                
                numar_curent += 1

if __name__ == "__main__":
    an_s = int(sys.argv[1]) if len(sys.argv) >= 3 else 2000
    an_f = int(sys.argv[2]) if len(sys.argv) >= 3 else 2026
    
    descarca_monitoare_pdf(an_start=an_s, an_stop=an_f)
