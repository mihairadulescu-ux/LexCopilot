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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
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
# CORE CRAWLER MULTI-SUFIX (Bis, Tris, Quatro, S)
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

    MAX_NUMERE_AN = 1300 
    
    print("🧠 Pasul 2: Calculare diferențe și identificare fișiere lipsă...", flush=True)
    coada_descarcare = []
    
    # Definirea variantelor pe care le căutăm
    variante_sufixe = [
        {"sufix": "", "tip": "simplu"},
        {"sufix": "Bis", "tip": "bis"},
        {"sufix": "Tris", "tip": "tris"},
        {"sufix": "Quatro", "tip": "quatro"},
        {"sufix": "S", "tip": "s"}
    ]
    
    for an in range(an_start, an_stop + 1):
        numere_existente_an = []
        for f in fisiere_drive:
            if f.startswith(f"MO_PI_{an}_"):
                try:
                    num_str = f.split('_')[3].split('.')[0]
                    # Eliminăm sufixele cunoscute pentru a obține doar numărul curat
                    for suf in ['Bis', 'Tris', 'Quatro', 'S']:
                        num_str = num_str.replace(suf, '')
                    numere_existente_an.append(int(num_str))
                except (IndexError, ValueError):
                    continue
                    
        max_numar_existent = max(numere_existente_an) if numere_existente_an else 0
        limita_scanare = MAX_NUMERE_AN if an >= 2025 else min(max_numar_existent + 30, MAX_NUMERE_AN)
        
        for n in range(1, limita_scanare + 1):
            for var in variante_sufixe:
                numar_complet = f"{n}{var['sufix']}" if var["sufix"] else str(n)
                nume_pdf = f"MO_PI_{an}_{numar_complet}.pdf"
                
                if nume_pdf not in fisiere_drive:
                    coada_descarcare.append({
                        "an": an, 
                        "numar": numar_complet, 
                        "nume_pdf": nume_pdf, 
                        "tip": var["tip"]
                    })

    total_lipsa = len(coada_descarcare)
    if total_lipsa == 0:
        print("🎉 Toate fișierele sunt la zi! Nimic de descărcat.", flush=True)
        return
        
    print(f"🚀 Pasul 3: Începem descărcarea a {total_lipsa} fișiere în coadă...", flush=True)
    
    director_temp = Path("./temp_pdf_download")
    director_temp.mkdir(exist_ok=True)
    
    timeout_config = httpx.Timeout(timeout=120.0, connect=20.0, read=120.0)
    erori_consecutive_an = {}
    ani_finalizati = set() 
    fisiere_esuate = []
    
    for idx, item in enumerate(coada_descarcare, 1):
        an = item["an"]
        numar_cerut = item["numar"]
        nume_pdf = item["nume_pdf"]
        
        if an in ani_finalizati:
            continue
            
        print(f"⏳ [{idx}/{total_lipsa}] Se caută pe server: {nume_pdf}...", flush=True)
        
        url = url_template.format(numar=numar_cerut, an=an)
        descarcat_ok = False
        era_404 = False
        incercari = 0
        
        cale_locala = director_temp / nume_pdf
        cale_temp = director_temp / f"{nume_pdf}.part"
        
        while incercari < 3:
            try:
                time.sleep(random.uniform(2.5, 4.5))
                
                headers = {
                    "User-Agent": random.choice(USER_AGENTS), 
                    "Referer": "https://monitoruloficial.ro/e-monitor/"
                }
                
                dimensiune_partiala = 0
                if cale_temp.exists():
                    dimensiune_partiala = cale_temp.stat().st_size
                    if dimensiune_partiala > 0:
                        headers["Range"] = f"bytes={dimensiune_partiala}-"
                
                with httpx.Client(headers=headers, timeout=timeout_config, follow_redirects=True) as client:
                    with client.stream("GET", url) as response:
                        if response.status_code == 416:
                            if cale_temp.exists():
                                cale_temp.unlink()
                            dimensiune_partiala = 0
                            continue
                            
                        # Dacă fișierul nu există (404)
                        if response.status_code == 404:
                            era_404 = True
                            if item["tip"] == "simplu":
                                erori_consecutive_an[an] = erori_consecutive_an.get(an, 0) + 1
                                if erori_consecutive_an[an] >= 30:
                                    print(f"🏁 [Anulat inteligent] Anul {an} pare finalizat pe server (30 eșecuri consecutive). Sărim restul numerelor.", flush=True)
                                    ani_finalizati.add(an)
                            break
                            
                        if response.status_code in [500, 502, 503, 504]:
                            incercari += 1
                            time.sleep(20.0)
                            continue
                            
                        response.raise_for_status()
                        if "application/pdf" not in response.headers.get("Content-Type", ""):
                            break
                            
                        if item["tip"] == "simplu":
                            erori_consecutive_an[an] = 0
                        
                        mod_scriere = "ab" if (response.status_code == 206 and dimensiune_partiala > 0) else "wb"
                        if mod_scriere == "wb" and cale_temp.exists():
                            cale_temp.unlink()
                            
                        with open(cale_temp, mod_scriere) as f:
                            for chunk in response.iter_bytes(chunk_size=16384):
                                f.write(chunk)
                                
                        cale_temp.replace(cale_locala)
                        descarcat_ok = True
                        break
                        
            except Exception as e:
                incercari += 1
                print(f"⚠️ Problemă la descărcare {nume_pdf} (Încercarea {incercari}/3): {e}", flush=True)
                time.sleep(random.uniform(45.0, 75.0))
                
        if descarcat_ok:
            marime_mb = os.path.getsize(cale_locala) // 1024 // 1024
            print(f"📥 Descărcat cu succes: {nume_pdf} (~{marime_mb} MB)", flush=True)
            if incarca_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID):
                print(f"✅ Sincronizat în Google Drive.", flush=True)
            time.sleep(random.uniform(3.0, 6.0))
            
        elif era_404:
            # Creare fișier "scut" de 0 bytes pentru oricare variantă inexistentă
            if an not in ani_finalizati:
                print(f"ℹ️ {nume_pdf} -> Nu există (404). Generăm fișier de marcaj (0 bytes)...", flush=True)
                if cale_temp.exists():
                    cale_temp.unlink()
                
                with open(cale_locala, "wb") as f:
                    pass 
                
                if incarca_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID):
                    print(f"📝 Placeholder salvat în Drive pentru {nume_pdf}.", flush=True)
                time.sleep(random.uniform(1.5, 3.0))
        else:
            if an not in ani_finalizati:
                if cale_temp.exists():
                    cale_temp.unlink()
                if incercari >= 3:
                    print(f"⏭️ [Ocolit] Fișierul {nume_pdf} a fost ocolit după 3 încercări eșuate de rețea. Continuăm cu restul coadei...", flush=True)
                    fisiere_esuate.append(nume_pdf)

    if fisiere_esuate:
        print("\n⚠️ Rularea s-a încheiat cu câteva fișiere nefinalizate din cauza serverului:", flush=True)
        for f in fisiere_esuate:
            print(f"  - {f} (dimensiune prea mare / serverul a tăiat conexiunea)", flush=True)
    else:
        print("\n🎉 Rulare completă finalizată cu succes!", flush=True)

if __name__ == "__main__":
    an_s = int(sys.argv[1]) if len(sys.argv) >= 3 else 2000
    an_f = int(sys.argv[2]) if len(sys.argv) >= 3 else 2026
    descarca_monitoare_precalculat(an_start=an_s, an_stop=an_f)
