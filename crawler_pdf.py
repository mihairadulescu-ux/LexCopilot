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
# DESCARCARE SEGMENTATA - OPTIMIZATA ULTRA-SIGUR LA 20MB
# ======================================================================
def descarca_in_bucati_mari(url, cale_locala, cale_temp, total_bytes, timeout_config):
    # MODIFICARE: Segmente de 20 MB pentru stabilitate maximă pe conexiuni slabe/instabile
    dimensiune_segment = 20 * 1024 * 1024  # 20 MB
    print(f"🧩 Fișier uriaș detectat ({total_bytes // 1024 // 1024} MB). Aplicăm descărcarea segmentată în bucăți ultra-sigure de 20MB...", flush=True)
    
    if cale_temp.exists():
        cale_temp.unlink()
        
    for start_byte in range(0, total_bytes, dimensiune_segment):
        end_byte = min(start_byte + dimensiune_segment - 1, total_bytes - 1)
        print(f"   ↳ Cerem segmentul: {start_byte // 1024 // 1024}MB - {(end_byte + 1) // 1024 // 1024}MB...", end="", flush=True)
        
        incercari_segment = 0
        segment_descarcat = False
        
        while incercari_segment < 3 and not segment_descarcat:
            try:
                time.sleep(random.uniform(3.0, 5.0))
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Referer": "https://monitoruloficial.ro/e-monitor/",
                    "Range": f"bytes={start_byte}-{end_byte}"
                }
                
                with httpx.Client(headers=headers, timeout=timeout_config, follow_redirects=True) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    
                    with open(cale_temp, "ab") as f:
                        f.write(response.content)
                        
                    segment_descarcat = True
                    print(" OK!", flush=True)
                    
            except Exception as e:
                incercari_segment += 1
                print(f" Reîncercare segment ({incercari_segment}/3)...", flush=True)
                time.sleep(15.0)
                
        if not segment_descarcat:
            print(f"❌ Nu s-a putut descărca segmentul {start_byte}-{end_byte}.", flush=True)
            if cale_temp.exists():
                cale_temp.unlink()
            return False
            
    cale_temp.replace(cale_locala)
    return True

# ======================================================================
# CORE CRAWLER INTELIGENT MULTI-SUFIX
# ======================================================================
def descarca_monitoare_precalculat(an_start=2000, am_stop=2026):
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
    
    variante_sufixe = [
        {"sufix": "", "tip": "simplu"},
        {"sufix": "Bis", "tip": "bis"},
        {"sufix": "Tris", "tip": "tris"},
        {"sufix": "Quatro", "tip": "quatro"},
        {"sufix": "S", "tip": "s"}
    ]
    
    for an in range(an_start, am_stop + 1):
        numere_existente_an = []
        for f in fisiere_drive:
            if f.startswith(f"MO_PI_{an}_"):
                try:
                    num_str = f.split('_')[3].split('.')[0]
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
    
    timeout_config = httpx.Timeout(timeout=45.0, connect=10.0, read=45.0)
    erori_consecutive_an = {}
    ani_finalizati = set() 
    fisiere_esuate_protejate = []
    
    for idx, item in enumerate(coada_descarcare, 1):
        an = item["an"]
        numar_cerut = item["numar"]
        nume_pdf = item["nume_pdf"]
        
        este_protejat = item["tip"] in ["simplu", "bis"]
        este_special = item["tip"] not in ["simplu", "bis"]
        
        if an in ani_finalizati:
            continue
            
        print(f"⏳ [{idx}/{total_lipsa}] Se caută pe server: {nume_pdf}...", flush=True)
        
        url = url_template.format(numar=numar_cerut, an=an)
        descarcat_ok = False
        creeaza_fantomă = False
        incercari = 0
        limită_reincercări = 3 if este_protejat else 1
        
        cale_locala = director_temp / nume_pdf
        cale_temp = director_temp / f"{nume_pdf}.part"
        
        while incercari < limită_reincercări:
            try:
                time.sleep(random.uniform(1.5, 3.0))
                
                headers = {
                    "User-Agent": random.choice(USER_AGENTS), 
                    "Referer": "https://monitoruloficial.ro/e-monitor/"
                }
                
                with httpx.Client(headers=headers, timeout=timeout_config, follow_redirects=True) as client:
                    head_res = client.head(url)
                    
                    if head_res.status_code == 404:
                        creeaza_fantomă = True
                        if item["tip"] == "simplu":
                            erori_consecutive_an[an] = erori_consecutive_an.get(an, 0) + 1
                            if erori_consecutive_an[an] >= 30:
                                print(f"🏁 [Anulat inteligent] Anul {an} pare finalizat pe server (30 eșecuri consecutive de 404). Sărim restul.", flush=True)
                                ani_finalizati.add(an)
                        break
                    
                    total_bytes = int(head_res.headers.get("Content-Length", 0))
                    
                    if total_bytes > 95 * 1024 * 1024:
                        descarcat_ok = descarca_in_bucati_mari(url, cale_locala, cale_temp, total_bytes, timeout_config)
                        break
                    
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        
                        if "application/pdf" not in response.headers.get("Content-Type", ""):
                            if not este_protejat:
                                print(f"💡 Serverul a trimis HTML în loc de PDF la fișier special. Marcăm ca absent.", flush=True)
                                creeaza_fantomă = True
                            else:
                                print(f"⚠️ Eroare: Serverul a trimis HTML în loc de PDF la un fișier PROTEJAT (Simplu/Bis). NU marcăm cu dummy!", flush=True)
                            break
                            
                        if item["tip"] == "simplu":
                            erori_consecutive_an[an] = 0
                        
                        if cale_temp.exists():
                            cale_temp.unlink()
                            
                        with open(cale_temp, "wb") as f:
                            for chunk in response.iter_bytes(chunk_size=16384):
                                f.write(chunk)
                                
                        cale_temp.replace(cale_locala)
                        descarcat_ok = True
                        break
                        
            except (httpx.ConnectError, httpx.ReadError, httpx.HTTPStatusError, Exception) as e:
                incercari += 1
                
                descriere_eroare = str(e) if len(str(e)) < 120 else str(e)[:120] + "..."
                print(f"⚠️ Problemă la descărcare {nume_pdf} (Încercarea {incercari}/{limită_reincercări}): {descriere_eroare}", flush=True)
                
                if este_special:
                    print(f"💡 Eroare de conexiune la fișier foarte rar (Tris/Quatro/S) -> Presupunem că nu există.", flush=True)
                    creeaza_fantomă = True
                    break
                    
                time.sleep(random.uniform(20.0, 40.0))
                
        if descarcat_ok:
            marime_mb = os.path.getsize(cale_locala) // 1024 // 1024
            print(f"📥 Descărcat cu succes: {nume_pdf} (~{marime_mb} MB)", flush=True)
            if incarca_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID):
                print(f"✅ Sincronizat în Google Drive.", flush=True)
            time.sleep(random.uniform(2.0, 4.0))
            
        elif creeaza_fantomă:
            if an not in ani_finalizati:
                print(f"ℹ️ Creăm fișier de marcaj (1 byte) în Drive pentru: {nume_pdf}...", flush=True)
                if cale_temp.exists():
                    cale_temp.unlink()
                
                with open(cale_locala, "w") as f:
                    f.write(" ") 
                
                if incarca_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID):
                    print(f"📝 Placeholder salvat în Drive.", flush=True)
                time.sleep(random.uniform(1.0, 2.0))
        else:
            if an not in ani_finalizati:
                if cale_temp.exists():
                    cale_temp.unlink()
                print(f"⏭️ [Ocolit protejat] Fișierul {nume_pdf} a fost ocolit pentru siguranță și va fi reîncercat tura următoare.", flush=True)
                fisiere_esuate_protejate.append(nume_pdf)

    if fisiere_esuate_protejate:
        print("\n⚠️ Rularea s-a încheiat. Următoarele fișiere importante (Simplu/Bis) au eșuat temporar și NU au fost marcate cu dummy (se vor descărca la rularea următoare):", flush=True)
        for f in fisiere_esuate_protejate:
            print(f"  - {f}", flush=True)
    else:
        print("\n🎉 Rularea completă s-a terminat cu succes!", flush=True)

if __name__ == "__main__":
    an_s = int(sys.argv[1]) if len(sys.argv) >= 3 else 2000
    an_f = int(sys.argv[2]) if len(sys.argv) >= 3 else 2026
    descarca_monitoare_precalculat(an_start=an_s, am_stop=an_f)
