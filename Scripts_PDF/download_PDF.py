import os
import sys
import time
import random
import io
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# ======================================================================
# CONFIGURARE GOOGLE DRIVE ȘI ANI DINAMICI (GITHUB MATRIX)
# ======================================================================
GOOGLE_DRIVE_FOLDER_ID = "1c8SEo8UrQVe6qgzPFGLXJFiMyLeI-r8D"
MAX_DOWNLOAD_WORKERS = 40  # Numărul de thread-uri pentru citirea paralelă a fișierelor dummy

START_YEAR = int(os.getenv("START_YEAR", "2000"))
END_YEAR = int(os.getenv("END_YEAR", "2026"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
]

def extrage_contor_bis(status_string):
    if not status_string:
        return 0
    cifre = "".join([c for c in status_string if c.isdigit()])
    if cifre:
        return int(cifre)
    return 0

def obtine_creds():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipsește secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    return Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])

def instantiaza_drive(creds=None):
    if not creds:
        creds = obtine_creds()
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def decodific_si_proceseaza_dummy(creds, f_id, nume):
    try:
        service = instantiaza_drive(creds)
        request = service.files().get_media(fileId=f_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            _, done = downloader.next_chunk()
        
        continut = fh.getvalue().decode('utf-8', errors='ignore').strip()
        
        if continut.isdigit() and 1 <= int(continut) <= 5:
            return nume, f"dummy_{continut}"
        else:
            return nume, "dummy_final"
    except Exception:
        return nume, "dummy_final"

def adu_fisiere_existente_in_drive(drive_service, folder_id, an_start, an_stop):
    existente = {}
    conditii_ani = " or ".join([f"name contains 'MO_PI_{an}_'" for an in range(an_start, an_stop + 1)])
    query = f"'{folder_id}' in parents and ({conditii_ani}) and trashed = false"
    
    page_token = None
    print(f"    ↳ Scanăm metadatele din Drive STRICT pentru anii {an_start} - {an_stop}...", flush=True)
    
    while True:
        response = drive_service.files().list(
            q=query, 
            spaces='drive',  # Forțează corelarea în indexul global
            fields="nextPageToken, files(id, name, size)", 
            pageToken=page_token, 
            pageSize=1000,
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True,
            corpora="allDrives"  # CRUCIAL: Caută nativ în Shared Drives fără 404 sau rezultate vide
        ).execute()
        
        for f in response.get("files", []):
            nume = f["name"]
            f_id = f["id"]
            size = int(f.get("size", 0))
            status = "ok"
            
            if size == 1:
                status = "dummy_verificabil"
                
            existente[nume] = {"id": f_id, "size": size, "status": status}
            
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    fisiere_de_verificat = [n for n, v in existente.items() if v["status"] == "dummy_verificabil"]
    if fisiere_de_verificat:
        total_verificabile = len(fisiere_de_verificat)
        print(f"    ↳ Am detectat {total_verificabile} fișiere dummy în intervalul cerut. Pornim citirea paralelă cu {MAX_DOWNLOAD_WORKERS} thread-uri...", flush=True)
        
        creds = obtine_creds()
        progres = 0
        
        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as executor:
            futures = {
                executor.submit(decodific_si_proceseaza_dummy, creds, existente[nume]["id"], nume): nume
                for nume in fisiere_de_verificat
            }
            
            for future in as_completed(futures):
                nume, status_rezultat = future.result()
                existente[nume]["status"] = status_rezultat
                
                progres += 1
                if progres % 500 == 0 or progres == total_verificabile:
                    print(f"      [Progres] Citit contor pentru {progres}/{total_verificabile} fișiere dummy...", flush=True)
                    
    return existente

def incarca_sau_actualizeaza_in_drive(drive_service, cale_locala, folder_id, file_id_existent=None):
    nume_fisier = cale_locala.name
    media = MediaFileUpload(str(cale_locala), mimetype='application/pdf', chunksize=1024*1024*5, resumable=True)
    try:
        if file_id_existent:
            request = drive_service.files().update(fileId=file_id_existent, media_body=media, supportsAllDrives=True)
        else:
            metadata = {'name': nume_fisier, 'parents': [folder_id]}
            request = drive_service.files().create(body=metadata, media_body=media, fields='id', supportsAllDrives=True)
            
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"    ↳ [Drive Upload] {int(status.progress() * 100)}% din {nume_fisier} trimis...", flush=True)
                
        if response.get('id'):
            cale_locala.unlink()
            return True
    except Exception as e:
        print(f"❌ [Drive Err] Eroare scriere/update {nume_fisier}: {e}", flush=True)
    return False

# ======================================================================
# CORE CRAWLER CORECTAT: REQUEST IERARHIC CURAT (GET)
# ======================================================================
def descarca_monitoare_precalculat(an_start=2000, am_stop=2026):
    url_template = "https://monitoruloficial.ro/Monitorul-Oficial--PI--{numar}--{an}.html"
    
    print(f"🔄 Pasul 1: Conectare la Google Drive (Interval de scanare: {an_start} - {am_stop})...", flush=True)
    try:
        drive_service = instantiaza_drive()
        inventar_drive = adu_fisiere_existente_in_drive(drive_service, GOOGLE_DRIVE_FOLDER_ID, an_start, am_stop)
        print(f"📊 Scanare finalizată. Detectate {len(inventar_drive)} înregistrări locale în cloud pe acest interval.", flush=True)
    except Exception as e:
        print(f"🛑 Eroare critică la inițializarea Google Drive: {e}", flush=True)
        return

    MAX_NUMERE_AN = 1350 
    print("🧠 Pasul 2: Calculare diferențe și identificare fișiere lipsă...", flush=True)
    coada_descarcare = []
    
    AN_CURENT_SISTEM = 2026
    
    for an in range(an_start, am_stop + 1):
        numere_existente_an = []
        for f in inventar_drive.keys():
            if f.startswith(f"MO_PI_{an}_"):
                try:
                    num_str = f.split('_')[3].split('.')[0]
                    for suf in ['Bis', 'Tris', 'Quater', 'S']:
                        num_str = num_str.replace(suf, '')
                    numere_existente_an.append(int(num_str))
                except (IndexError, ValueError):
                    continue
                    
        max_numar_existent = max(numere_existente_an) if numere_existente_an else 0
        
        if an < AN_CURENT_SISTEM:
            limata_scanare = MAX_NUMERE_AN
        else:
            limata_scanare = min(max_numar_existent + 50, MAX_NUMERE_AN)
            if limata_scanare < 100:
                limata_scanare = 100
        
        for n in range(1, limata_scanare + 1):
            for sufix, tip_var in [("", "simplu"), ("Bis", "bis"), ("S", "special")]:
                numar_complet = f"{n}{sufix}" if sufix else str(n)
                nume_pdf = f"MO_PI_{an}_{numar_complet}.pdf"
                
                trebuie_descarcat = False
                status_actual = None
                file_id_existent = None
                
                if nume_pdf not in inventar_drive:
                    trebuie_descarcat = True
                else:
                    meta = inventar_drive[nume_pdf]
                    file_id_existent = meta["id"]
                    if sufix == "Bis" and meta["status"].startswith("dummy_") and meta["status"] != "dummy_final":
                        trebuie_descarcat = True
                        status_actual = meta["status"]
                        
                if trebuie_descarcat:
                    coada_descarcare.append({
                        "an": an, 
                        "numar": numar_complet, 
                        "nume_pdf": nume_pdf, 
                        "tip": tip_var,
                        "file_id_existent": file_id_existent,
                        "status_actual": status_actual
                    })
            
            nume_bis_martor = f"MO_PI_{an}_{n}Bis.pdf"
            if nume_bis_martor in inventar_drive and inventar_drive[nume_bis_martor]["status"] == "ok":
                for sufix_rar, tip_rar in [("Tris", "tris"), ("Quater", "quater")]:
                    numar_complet_rar = f"{n}{sufix_rar}"
                    nume_pdf_rar = f"MO_PI_{an}_{numar_complet_rar}.pdf"
                    
                    if nume_pdf_rar not in inventar_drive:
                        coada_descarcare.append({
                            "an": an,
                            "numar": numar_complet_rar,
                            "nume_pdf": nume_pdf_rar,
                            "tip": "special",
                            "file_id_existent": None,
                            "status_actual": None
                        })

    total_lipsa = len(coada_descarcare)
    if total_lipsa == 0:
        print("\n🎉 Toate fișierele sunt la zi pentru acest interval! Nimic de descărcat.", flush=True)
        return
        
    print(f"\n🚀 Pasul 3: Începem descărcarea a {total_lipsa} fișiere în coadă...", flush=True)
    
    director_temp = Path("./temp_pdf_download")
    director_temp.mkdir(exist_ok=True)
    
    timeout_resilient = httpx.Timeout(timeout=300.0, connect=30.0)
    erori_consecutive_an = {}
    ani_finalizati = set() 
    fisiere_esuate_protejate = []
    
    for idx, item in enumerate(coada_descarcare, 1):
        an = item["an"]
        numar_cerut = item["numar"]
        nume_pdf = item["nume_pdf"]
        
        este_simplu = item["tip"] == "simplu"
        este_bis = item["tip"] == "bis"
        este_special = item["tip"] not in ["simplu", "bis"]
        
        if an in ani_finalizati:
            continue
            
        print(f"⏳ [{idx}/{total_lipsa}] Se solicită pe server: {nume_pdf}...", flush=True)
        
        url = url_template.format(numar=numar_cerut, an=an)
        descarcat_ok = False
        creeaza_fantomă = False
        valoare_fantomă = " "
        
        limită_reincercări = 1 if (este_special or este_bis) else 3
        incercari = 0
        
        cale_locala = director_temp / nume_pdf
        
        while incercari < limită_reincercări:
            try:
                sleep_time = random.uniform(1.0, 2.5) if incercari == 0 else random.uniform(5.0, 10.0)
                time.sleep(sleep_time)
                
                headers = {
                    "User-Agent": random.choice(USER_AGENTS), 
                    "Referer": "https://monitoruloficial.ro/e-monitor/"
                }
                
                with httpx.Client(headers=headers, timeout=timeout_resilient, follow_redirects=True) as client:
                    response = client.get(url)
                    
                    if response.status_code == 404:
                        creeaza_fantomă = True
                        valoare_fantomă = " "
                        if este_simplu:
                            erori_consecutive_an[an] = erori_consecutive_an.get(an, 0) + 1
                            if erori_consecutive_an[an] >= 60:
                                print(f"🏁 [Finalizat] Anul {an} pare încheiat pe server (60 eșecuri consecutive la rând).", flush=True)
                                ani_finalizati.add(an)
                        break
                        
                    response.raise_for_status()
                    content_type = response.headers.get("Content-Type", "").lower()
                    
                    if "application/pdf" in content_type or len(response.content) > 20000:
                        with open(cale_locala, "wb") as f:
                            f.write(response.content)
                        
                        if este_simplu:
                            erori_consecutive_an[an] = 0
                        
                        descarcat_ok = True
                        break
                    else:
                        if este_special:
                            creeaza_fantomă = True
                            valoare_fantomă = " "
                            break
                        elif este_bis:
                            creeaza_fantomă = True
                            contor_vechi = extrage_contor_bis(item["status_actual"])
                            urmatorul_contor = contor_vechi + 1
                            valoare_fantomă = str(urmatorul_contor) if urmatorul_contor < 6 else " "
                            break
                        else:
                            raise IOError("Serverul a returnat pagină web în loc de documentul binar.")
                            
            except Exception as e:
                incercari += 1
                if incercari >= limită_reincercări:
                    print(f"⚠️ Încercări epuizate pentru {nume_pdf}: {str(e)[:100]}", flush=True)
                    if este_special or este_bis:
                        creeaza_fantomă = True
                        valoare_fantomă = " "
                else:
                    time.sleep(3.0)
        
        if descarcat_ok:
            marime_mb = os.path.getsize(cale_locala) / 1024 / 1024
            print(f"📥 Descărcat complet: {nume_pdf} (~{marime_mb:.2f} MB)", flush=True)
            if incarca_sau_actualizeaza_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID, item["file_id_existent"]):
                print(f"✅ Sincronizat cu succes în Google Drive.", flush=True)
            time.sleep(random.uniform(1.0, 2.0))
            
        elif creeaza_fantomă:
            if an not in ani_finalizati:
                with open(cale_locala, "w") as f:
                    f.write(valoare_fantomă) 
                
                if incarca_sau_actualizeaza_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID, item["file_id_existent"]):
                    print(f"📝 Placeholder salvat în Drive pentru {nume_pdf}.", flush=True)
        else:
            if an not in ani_finalizati:
                print(f"⏭️ [Eșuat temporar] Fișierul {nume_pdf} va fi reîncercat tura următoare.", flush=True)
                fisiere_esuate_protejate.append({"nume": nume_pdf, "url": url})

    if fisiere_esuate_protejate:
        cale_fisier_manual = Path("liste_descarcare_manuala.txt")
        try:
            with open(cale_fisier_manual, "w", encoding="utf-8") as f_manual:
                f_manual.write("# FIȘIERE PENTRU DESCĂRCARE MANUALĂ\n\n")
                for f in fisiere_esuate_protejate:
                    f_manual.write(f"{f['nume']} -> {f['url']}\n")
        except Exception:
            pass
    print("\n🎉 Rularea nocturnă s-a finalizat!", flush=True)

# ======================================================================
# PARSER ROBUST DE INTERVALE (FLEXIBIL PENTRU MATRICEA YML)
# ======================================================================
if __name__ == "__main__":
    argumente_numerice = []
    
    for arg in sys.argv[1:]:
        piese = arg.split()
        for piesa in piese:
            if piesa.isdigit():
                argumente_numerice.append(int(piesa))

    if len(argumente_numerice) == 1:
        an_s = argumente_numerice[0]
        an_f = argumente_numerice[0]
    elif len(argumente_numerice) >= 2:
        an_s = argumente_numerice[0]
        an_f = argumente_numerice[1]
    else:
        an_s = START_YEAR
        an_f = END_YEAR
        
    print(f"🎯 [Config Matrix] Rulăm scriptul izolat pentru intervalul: {an_s} - {an_f}", flush=True)
    descarca_monitoare_precalculat(an_start=an_s, am_stop=an_f)
