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
# CONFIGURARE GOOGLE DRIVE
# ======================================================================
GOOGLE_DRIVE_FOLDER_ID = "1c8SEo8UrQVe6qgzPFGLXJFiMyLeI-r8D"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
]

def instantiaza_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    import json
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds)

def adu_fisiere_existente_in_drive(drive_service, folder_id):
    existente = set()
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    while True:
        response = drive_service.files().list(
            q=query, fields="nextPageToken, files(name)", pageToken=page_token, pageSize=1000,
            supportsAllDrives=True, includeItemsFromAllDrives=True
        ).execute()
        for f in response.get("files", []):
            existente.add(f["name"])
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
    return existente

def incarca_in_drive(drive_service, cale_locala, folder_id):
    nume_fisier = cale_locala.name
    metadata = {'name': nume_fisier, 'parents': [folder_id]}
    media = MediaFileUpload(str(cale_locala), mimetype='application/pdf', resumable=True)
    try:
        file_drive = drive_service.files().create(body=metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
        if file_drive.get('id'):
            cale_locala.unlink()
            return True
    except Exception as e:
        print(f"❌ [Drive Err] Eroare incarcare {nume_fisier}: {e}", flush=True)
    return False

# ======================================================================
# CORE CRAWLER OPTIMIZAT PRIN DIFERENȚĂ DE SETURI
# ======================================================================
def descarca_monitoare_precalculat(an_start=2000, an_stop=2026):
    url_template = "https://monitoruloficial.ro/Monitorul-Oficial--PI--{numar}--{an}.html"
    
    print("🔄 Pasul 1: Conectare la Google Drive și preluare index...", flush=True)
    try:
        drive_service = instantiaza_drive()
        fisiere_drive = adu_fisiere_existente_in_drive(drive_service, GOOGLE_DRIVE_FOLDER_ID)
        print(f"📊 Detectate {len(fisiere_drive)} PDF-uri salvate deja în cloud.", flush=True)
    except Exception as e:
        print(f"🛑 Eroare critică la inițializarea Google Drive: {e}", flush=True)
        return

    # Presupunem un număr maxim realist de monitoare pe an (ex: 1300) pentru a genera lista ideală
    MAX_NUMERE_AN = 1300 
    
    print("🧠 Pasul 2: Calculare diferențe și identificare fișiere lipsă...", flush=True)
    coada_descarcare = []
    
    for an in range(an_start, an_stop + 1):
        # Aflăm care este cel mai mare număr de bază pe care îl avem deja în Drive pentru acest an
        numere_existente_an = [
            int(f.split('_')[3].split('.')[0].replace('Bis', '')) 
            for f in fisiere_drive 
            if f.startswith(f"MO_PI_{an}_")
        ]
        max_numar_existent = max(numere_existente_an) if numere_existente_an else 0
        
        # Limita superioară: mergem până la max_numar_existent + 30 (marja de siguranță pentru numere lipsă)
        # Pentru anii curenți/recenți, forțăm scanarea completă până la limita maximă teoretică
        limita_scanare = MAX_NUMERE_AN if an >= 2025 else min(max_numar_existent + 30, MAX_NUMERE_AN)
        
        for n in range(1, limita_scanare + 1):
            nume_simplu = f"MO_PI_{an}_{n}.pdf"
            nume_bis = f"MO_PI_{an}_{n}Bis.pdf"
            
            # Adăugăm în coada de lucru DOAR dacă nu există în Drive
            if nume_simplu not in fisiere_drive:
                coada_descarcare.append({"an": an, "numar": str(n), "nume_pdf": nume_simplu, "tip": "simplu"})
                
            if nume_bis not in fisiere_drive:
                coada_descarcare.append({"an": an, "numar": f"{n}Bis", "nume_pdf": nume_bis, "tip": "bis"})

    total_lipsa = len(coada_descarcare)
    if total_lipsa == 0:
        print("🎉 Toate fișierele sunt la zi! Nimic de descărcat.", flush=True)
        return
        
    print(f"🚀 Pasul 3: Începem descărcarea a {total_lipsa} fișiere identificate ca lipsă...", flush=True)
    
    director_temp = Path("./temp_pdf_download")
    director_temp.mkdir(exist_ok=True)
    
    timeout_config = httpx.Timeout(45.0, connect=15.0)
    erori_consecutive_an = {} # Păstrăm evidența eșecurilor per an pentru a nu merge la infinit
    
    for idx, item in enumerate(coada_descarcare, 1):
        an = item["an"]
        numar_cerut = item["numar"]
        nume_pdf = item["nume_pdf"]
        
        # Dacă pentru anul respectiv am dat deja de peste 30 de erori la numere simple, înseamnă că anul s-a terminat pe server
        if erori_consecutive_an.get(an, 0) >= 30 and item["tip"] == "simplu":
            continue
            
        print(f"⏳ [{idx}/{total_lipsa}] Se caută pe server: {nume_pdf}...", flush=True)
        
        url = url_template.format(numar=numar_cerut, an=an)
        headers = {"User-Agent": random.choice(USER_AGENTS), "Referer": "https://monitoruloficial.ro/e-monitor/"}
        
        descarcat_ok = False
        incercari = 0
        
        while incercari < 3:
            try:
                time.sleep(random.uniform(2.0, 4.0)) # Delay anti-ban obligatoriu
                
                with httpx.Client(headers=headers, timeout=timeout_config, follow_redirects=True) as client:
                    with client.stream("GET", url) as response:
                        if response.status_code == 404:
                            if item["tip"] == "simplu":
                                erori_consecutive_an[an] = erori_consecutive_an.get(an, 0) + 1
                            break
                            
                        if response.status_code in [500, 502, 503, 504]:
                            incercari += 1
                            time.sleep(15.0)
                            continue
                            
                        response.raise_for_status()
                        if "application/pdf" not in response.headers.get("Content-Type", ""):
                            break
                            
                        # Resetăm erorile pentru anul ăsta dacă am găsit un fișier valid
                        if item["tip"] == "simplu":
                            erori_consecutive_an[an] = 0
                            
                        cale_locala = director_temp / nume_pdf
                        cale_temp = director_temp / f"{nume_pdf}.part"
                        
                        with open(cale_temp, "wb") as f:
                            for chunk in response.iter_bytes(chunk_size=65536):
                                f.write(chunk)
                                
                        cale_temp.replace(cale_locala)
                        descarcat_ok = True
                        break
            except Exception as e:
                incercari += 1
                print(f"⚠️ Eroare la {nume_pdf} (incercarea {incercari}/3): {e}", flush=True)
                time.sleep(60.0)
                
        if descarcat_ok:
            print(f"📥 Descărcat cu succes: {nume_pdf}", flush=True)
            if incarca_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID):
                print(f"✅ Sincronizat în Google Drive.", flush=True)
            time.sleep(random.uniform(3.0, 5.0))
        else:
            # Dacă e număr simplu și a dat 404, raportăm discret
            if erori_consecutive_an.get(an, 0) < 30 and item["tip"] == "simplu":
                print(f"ℹ️ {nume_pdf} nu a fost găsit pe server.", flush=True)

if __name__ == "__main__":
    an_s = int(sys.argv[1]) if len(sys.argv) >= 3 else 2000
    an_f = int(sys.argv[2]) if len(sys.argv) >= 3 else 2026
    descarca_monitoare_pdf = descarca_monitoare_precalculat(an_start=an_s, an_stop=an_f)


