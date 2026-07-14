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

# Listă de User-Agents moderni pentru rotație automată
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
]

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
    
    # Timeout mărit pentru a permite descărcări lente și sigure
    timeout_config = httpx.Timeout(45.0, connect=15.0)
    
    for an in range(an_start, an_stop + 1):
        print(f"\n=================== PROCESĂM ANUL {an} ===================", flush=True)
        
        numar_curent = 1
        erori_consecutive = 0
        limita_erori = 30 # 30 de numere absente consecutive = an terminat
        
        while True:
            # Determinăm mai întâi dacă numărul de bază (simplu) există local sau în cloud
            nume_baza_pdf = f"MO_PI_{an}_{numar_curent}.pdf"
            baza_exista_in_drive = nume_baza_pdf in fisiere_drive
            
            # Verificăm dacă numărul de bază a fost găsit pe server în această rulare
            baza_gasit_acum = False
            
            # Pasul 1: Încercăm numărul de bază (ex: "10")
            url_baza = url_template.format(numar=str(numar_curent), an=an)
            
            if baza_exista_in_drive:
                print(f"☁️ [Există în Drive] {nume_baza_pdf}", flush=True)
                baza_gasit_acum = True
                erori_consecutive = 0
            else:
                # Rotire dinamică de browser pentru a ocoli detecția WAF
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Referer": "https://monitoruloficial.ro/e-monitor/"
                }
                
                # Încercăm descărcarea numărului de bază cu retry robust
                descarcat_cu_succes = False
                incercari_conexiune = 0
                max_incercari_conexiune = 3
                
                while incercari_conexiune < max_incercari_conexiune:
                    try:
                        # Pauză politicoasă înainte de a apela serverul
                        time.sleep(random.uniform(2.0, 4.0))
                        
                        with httpx.Client(headers=headers, timeout=timeout_config, follow_redirects=True) as client:
                            with client.stream("GET", url_baza) as response:
                                if response.status_code == 404:
                                    break  # Nu există baza, oprim bucla retry
                                
                                if response.status_code in [500, 502, 503, 504]:
                                    print(f"⚠️ [Server Error {response.status_code}] La {numar_curent}/{an}. Reîncercare...", flush=True)
                                    incercari_conexiune += 1
                                    time.sleep(15.0)
                                    continue
                                
                                response.raise_for_status()
                                
                                tip_continut = response.headers.get("Content-Type", "")
                                if "application/pdf" not in tip_continut:
                                    break  # Redirect ciudat, nu e un PDF real
                                
                                # Dacă am ajuns aici, documentul este de încredere
                                baza_gasit_acum = True
                                erori_consecutive = 0
                                
                                cale_finala_locala = director_temp / nume_baza_pdf
                                cale_temporara = director_temp / f"{nume_baza_pdf}.part"
                                
                                with open(cale_temporara, "wb") as f_temp:
                                    for chunk in response.iter_bytes(chunk_size=65536):
                                        f_temp.write(chunk)
                                
                                cale_temporara.replace(cale_finala_locala)
                                print(f"📥 Descărcat local: {nume_baza_pdf}", flush=True)
                                descarcat_cu_succes = True
                                break
                                
                    except (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.HTTPError) as e:
                        incercari_conexiune += 1
                        print(f"⚠️ [Rețea/SSL Err] Probleme la baza {numar_curent}/{an} (Incercarea {incercari_conexiune}/{max_incercari_conexiune}): {e}", flush=True)
                        
                        # Timp de răcire considerabil în caz de blocaj sever al IP-ului (Cool-off)
                        print("⏳ Aplicăm timp de răcire de 90 de secunde pentru resetarea conexiunii...", flush=True)
                        time.sleep(90.0)
                
                # Sincronizare în Drive
                if descarcat_cu_succes:
                    if incarca_in_drive(drive_service, cale_finala_locala, GOOGLE_DRIVE_FOLDER_ID):
                        print(f"✅ [Sincronizat Drive] {nume_baza_pdf}", flush=True)
                    time.sleep(random.uniform(4.0, 7.0))

            # Pasul 2: Procesăm sufixele speciale (Bis, Tris, Quater, S) DOAR dacă numărul de bază a fost găsit sau exista deja
            # Dacă numărul de bază NU există pe server (404), este inutil să scanăm variantele (economie de timp și trafic!)
            document_gasit_pe_server = baza_gasit_acum
            
            if baza_gasit_acum or baza_exista_in_drive:
                sufixe = ["Bis", "Tris", "Quater", "S"]
                
                for sufix in sufixe:
                    varianta = f"{numar_curent}{sufix}"
                    nume_sufix_pdf = f"MO_PI_{an}_{varianta}.pdf"
                    
                    if nume_sufix_pdf in fisiere_drive:
                        print(f"☁️ [Există în Drive] {nume_sufix_pdf}", flush=True)
                        document_gasit_pe_server = True
                        continue
                        
                    url_sufix = url_template.format(numar=varianta, an=an)
                    headers_sufix = {
                        "User-Agent": random.choice(USER_AGENTS),
                        "Referer": "https://monitoruloficial.ro/e-monitor/"
                    }
                    
                    descarcat_sufix_succes = False
                    incercari_sufix = 0
                    
                    while incercari_sufix < max_incercari_conexiune:
                        try:
                            # Pauză foarte scurtă între sufixe pentru protecție anti-flood
                            time.sleep(random.uniform(1.0, 2.5))
                            
                            with httpx.Client(headers=headers_sufix, timeout=timeout_config, follow_redirects=True) as client:
                                with client.stream("GET", url_sufix) as response:
                                    if response.status_code == 404:
                                        break
                                    
                                    if response.status_code in [500, 502, 503, 504]:
                                        incercari_sufix += 1
                                        time.sleep(15.0)
                                        continue
                                    
                                    response.raise_for_status()
                                    
                                    tip_continut = response.headers.get("Content-Type", "")
                                    if "application/pdf" not in tip_continut:
                                        break
                                    
                                    document_gasit_pe_server = True
                                    
                                    cale_finala_locala = director_temp / nume_sufix_pdf
                                    cale_temporara = director_temp / f"{nume_sufix_pdf}.part"
                                    
                                    with open(cale_temporara, "wb") as f_temp:
                                        for chunk in response.iter_bytes(chunk_size=65536):
                                            f_temp.write(chunk)
                                            
                                    cale_temporara.replace(cale_finala_locala)
                                    print(f"📥 Descărcat local: {nume_sufix_pdf}", flush=True)
                                    descarcat_sufix_succes = True
                                    break
                                    
                        except (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.HTTPError) as e:
                            incercari_sufix += 1
                            print(f"⚠️ [Rețea/SSL Err] Probleme la varianta {varianta}/{an} (Incercarea {incercari_sufix}/{max_incercari_conexiune}): {e}", flush=True)
                            print("⏳ Aplicăm timp de răcire de 90 de secunde...", flush=True)
                            time.sleep(90.0)
                            
                    # Sincronizare sufix în Drive
                    if descarcat_sufix_succes:
                        if incarca_in_drive(drive_service, cale_finala_locala, GOOGLE_DRIVE_FOLDER_ID):
                            print(f"✅ [Sincronizat Drive] {nume_sufix_pdf}", flush=True)
                        time.sleep(random.uniform(4.0, 7.0))
            
            # Pasul 3: Logica de oprire a anului
            if not document_gasit_pe_server:
                erori_consecutive += 1
                # Afișăm în log progresul eșecurilor consecutive pentru a ști cât mai avem până la oprire
                print(f"❌ Numărul {numar_curent}/{an} nu a fost găsit. Contor eșecuri: {erori_consecutive}/{limita_erori}", flush=True)
            
            if erori_consecutive >= limita_erori:
                print(f"🏁 [Sfârșit de an] Anul {an} s-a încheiat după {limita_erori} numere consecutive complet absente.", flush=True)
                break
            
            numar_curent += 1

if __name__ == "__main__":
    an_s = int(sys.argv[1]) if len(sys.argv) >= 3 else 2000
    an_f = int(sys.argv[2]) if len(sys.argv) >= 3 else 2026
    
    descarca_monitoare_pdf(an_start=an_s, an_stop=an_f)
