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

# Preluăm anii din mediu (GitHub Actions) sau din argumente de consolă.
# Dacă nu sunt definite, pornesc implicit pe tot intervalul de siguranță.
START_YEAR = int(os.getenv("START_YEAR", "2000"))
END_YEAR = int(os.getenv("END_YEAR", "2026"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
]

def extrage_contor_bis(status_string):
    """
    Extrage în siguranță numărul contorului din stări precum 'dummy_1', 'dummy_2' sau 'dummy_verificabil'.
    Dacă nu găsește cifre sau starea nu e validă, returnează 0 (începe contorizarea de la zero).
    """
    if not status_string:
        return 0
    cifre = "".join([c for c in status_string if c.isdigit()])
    if cifre:
        return int(cifre)
    return 0

def obtine_creds():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    return Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])

def instantiaza_drive(creds=None):
    if not creds:
        creds = obtine_creds()
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def decodific_si_proceseaza_dummy(creds, f_id, nume):
    """Rulează în interiorul unui thread pentru a citi conținutul unui singur fișier dummy."""
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
    
    # CONSTRUIRE QUERY PARȚIAL: Cerem doar fișierele din anii alocați acestui workflow!
    # Format: (name contains 'MO_PI_2001_' or name contains 'MO_PI_2002_')
    conditii_ani = " or ".join([f"name contains 'MO_PI_{an}_'" for an in range(an_start, an_stop + 1)])
    query = f"'{folder_id}' in parents and ({conditii_ani}) and trashed = false"
    
    page_token = None
    print(f"   ↳ Scanăm metadatele din Drive STRICT pentru anii {an_start} - {an_stop}...", flush=True)
    
    while True:
        response = drive_service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name, size)", 
            pageToken=page_token, 
            pageSize=1000,
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
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
        print(f"   ↳ Am detectat {total_verificabile} fișiere dummy în intervalul cerut. Pornim citirea paralelă cu {MAX_DOWNLOAD_WORKERS} thread-uri...", flush=True)
        
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
                print(f"   ↳ [Drive Upload] {int(status.progress() * 100)}% din {nume_fisier} trimis...", flush=True)
                
        if response.get('id'):
            cale_locala.unlink()
            return True
    except Exception as e:
        print(f"❌ [Drive Err] Eroare scriere/update {nume_fisier}: {e}", flush=True)
    return False


# ======================================================================
# CORE CRAWLER INTELIGENT CU TIMEOUT EXTINS PENTRU FIȘIERE MARI
# ======================================================================
def descarca_monitoare_precalculat(an_start=2000, am_stop=2026):
    url_template = "https://monitoruloficial.ro/Monitorul-Oficial--PI--{numar}--{an}.html"
    
    print(f"🔄 Pasul 1: Conectare la Google Drive (Interval de scanare: {an_start} - {am_stop})...", flush=True)
    try:
        drive_service = instantiaza_drive()
        # Pasăm intervalul anilor pentru a filtra căutarea direct în cloud!
        inventar_drive = adu_fisiere_existente_in_drive(drive_service, GOOGLE_DRIVE_FOLDER_ID, an_start, am_stop)
        print(f"📊 Scanare finalizată. Detectate {len(inventar_drive)} înregistrări locale în cloud pe acest interval.", flush=True)
    except Exception as e:
        print(f"🛑 Eroare critică la inițializarea Google Drive: {e}", flush=True)
        return

    MAX_NUMERE_AN = 1350 
    
    print("🧠 Pasul 2: Calculare diferențe și identificare fișiere lipsă...", flush=True)
    coada_descarcare = []
    
    variante_sufixe = [
        {"sufix": "", "tip": "simplu"},
        {"sufix": "Bis", "tip": "bis"},
        {"sufix": "Tris", "tip": "tris"},
        {"sufix": "Quatro", "tip": "quatro"},
        {"sufix": "S", "tip": "s"}
    ]
    
    AN_CURENT_SISTEM = 2026
    
    for an in range(an_start, am_stop + 1):
        numere_existente_an = []
        for f in inventar_drive.keys():
            if f.startswith(f"MO_PI_{an}_"):
                try:
                    num_str = f.split('_')[3].split('.')[0]
                    for suf in ['Bis', 'Tris', 'Quatro', 'S']:
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
            for var in variante_sufixe:
                numar_complet = f"{n}{var['sufix']}" if var["sufix"] else str(n)
                nume_pdf = f"MO_PI_{an}_{numar_complet}.pdf"
                
                trebuie_descarcat = False
                status_actual = None
                file_id_existent = None
                
                if nume_pdf not in inventar_drive:
                    trebuie_descarcat = True
                else:
                    meta = inventar_drive[nume_pdf]
                    file_id_existent = meta["id"]
                    if var["tip"] == "bis" and meta["status"].startswith("dummy_") and meta["status"] != "dummy_final":
                        trebuie_descarcat = True
                        status_actual = meta["status"]
                    else:
                        if var["tip"] == "simplu" or meta["status"] == "ok":
                            pass
                
                if trebuie_descarcat:
                    coada_descarcare.append({
                        "an": an, 
                        "numar": numar_complet, 
                        "nume_pdf": nume_pdf, 
                        "tip": var["tip"],
                        "file_id_existent": file_id_existent,
                        "status_actual": status_actual
                    })

    total_lipsa = len(coada_descarcare)
    if total_lipsa == 0:
        print("\n🎉 Toate fișierele sunt la zi pentru acest interval! Nimic de descărcat.", flush=True)
        return
        
    print(f"\n🚀 Pasul 3: Începem descărcarea a {total_lipsa} fișiere în coadă...", flush=True)
    
    director_temp = Path("./temp_pdf_download")
    director_temp.mkdir(exist_ok=True)
    
    timeout_resilient = httpx.Timeout(timeout=360.0, connect=30.0, read=360.0)
    
    erori_consecutive_an = {}
    succese_in_an = {}
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
            
        print(f"⏳ [{idx}/{total_lipsa}] Se caută pe server: {nume_pdf}...", flush=True)
        
        url = url_template.format(numar=numar_cerut, an=an)
        descarcat_ok = False
        creeaza_fantomă = False
        valoare_fantomă = " "
        
        limită_reincercări = 1 if (este_special or este_bis) else 4
        incercari = 0
        
        cale_locala = director_temp / nume_pdf
        cale_temp = director_temp / f"{nume_pdf}.part"
        
        while incercari < limită_reincercări:
            try:
                sleep_time = random.uniform(1.5, 3.0) if incercari == 0 else random.uniform(10.0, 20.0) * incercari
                time.sleep(sleep_time)
                
                headers = {
                    "User-Agent": random.choice(USER_AGENTS), 
                    "Referer": "https://monitoruloficial.ro/e-monitor/"
                }
                
                if cale_temp.exists():
                    cale_temp.unlink()
                
                with httpx.Client(headers=headers, timeout=timeout_resilient, follow_redirects=True) as client:
                    with client.stream("GET", url) as response:
                        
                        if response.status_code == 404:
                            creeaza_fantomă = True
                            valoare_fantomă = " "
                            if este_simplu:
                                erori_consecutive_an[an] = erori_consecutive_an.get(an, 0) + 1
                                if erori_consecutive_an[an] >= 60 and succese_in_an.get(an, 0) > 10:
                                    print(f"🏁 [Anulat inteligent] Anul {an} pare finalizat pe server (60 eșecuri consecutive). Sărim restul.", flush=True)
                                    ani_finalizati.add(an)
                            break
                        
                        response.raise_for_status()
                        
                        content_type = response.headers.get("Content-Type", "").lower()
                        if "application/pdf" not in content_type:
                            if este_special:
                                creeaza_fantomă = True
                                valoare_fantomă = " "
                            elif este_bis:
                                creeaza_fantomă = True
                                contor_vechi = extrage_contor_bis(item["status_actual"])
                                urmatorul_contor = contor_vechi + 1
                                valoare_fantomă = str(urmatorul_contor) if urmatorul_contor < 6 else " "
                                
                                text_afisat = valoare_fantomă if valoare_fantomă != " " else "[Abandonat (spațiu)]"
                                print(f"💡 Serverul a trimis HTML. Incrementăm contorul Bis la: {text_afisat}", flush=True)
                            else:
                                print(f"⚠️ Eroare: HTML primit la un fișier SIMPLU. Îl ocolim fără dummy.", flush=True)
                            break
                        
                        total_bytes = 0
                        with open(cale_temp, "wb") as f:
                            for chunk in response.iter_bytes(chunk_size=131072):
                                f.write(chunk)
                                total_bytes += len(chunk)
                                
                        if total_bytes > 0:
                            if este_simplu:
                                erori_consecutive_an[an] = 0
                                succese_in_an[an] = succese_in_an.get(an, 0) + 1
                            
                            cale_temp.replace(cale_locala)
                            descarcat_ok = True
                            break
                        else:
                            raise IOError("Fișierul descărcat are dimensiune zero.")
                                
            except (httpx.ConnectError, httpx.ReadError, httpx.HTTPStatusError, Exception) as e:
                incercari += 1
                descriere_eroare = str(e) if len(str(e)) < 120 else str(e)[:120] + "..."
                print(f"⚠️ Problemă la descărcare {nume_pdf} (Încercarea {incercari}/{limită_reincercări}): {descriere_eroare}", flush=True)
                
                if este_special:
                    print(f"💡 Eroare la fișier special -> Presupunem neexistent.", flush=True)
                    creeaza_fantomă = True
                    valoare_fantomă = " "
                    break
                elif este_bis:
                    creeaza_fantomă = True
                    contor_vechi = extrage_contor_bis(item["status_actual"])
                    urmatorul_contor = contor_vechi + 1
                    valoare_fantomă = str(urmatorul_contor) if urmatorul_contor < 6 else " "
                    
                    text_afisat = valoare_fantomă if valoare_fantomă != " " else "[Abandonat (spațiu)]"
                    print(f"💡 Eroare conexiune pentru Bis. Incrementăm contorul la: {text_afisat}", flush=True)
                    break
                
                time.sleep(random.uniform(15.0, 30.0))
                
        if descarcat_ok:
            marime_mb = os.path.getsize(cale_locala) / 1024 / 1024
            print(f"📥 Descărcat complet: {nume_pdf} (~{marime_mb:.2f} MB)", flush=True)
            if incarca_sau_actualizeaza_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID, item["file_id_existent"]):
                print(f"✅ Sincronizat cu succes în Google Drive.", flush=True)
            time.sleep(random.uniform(2.0, 4.0))
            
        elif creeaza_fantomă:
            if an not in ani_finalizati:
                if cale_temp.exists():
                    cale_temp.unlink()
                
                with open(cale_locala, "w") as f:
                    f.write(valoare_fantomă) 
                
                text_stare = f"contor '{valoare_fantomă}'" if valoare_fantomă != " " else "spațiu final (abandonat)"
                print(f"ℹ️ Actualizăm dummy în Drive ({text_stare}) pentru: {nume_pdf}...", flush=True)
                
                if incarca_sau_actualizeaza_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID, item["file_id_existent"]):
                    print(f"📝 Placeholder salvat.", flush=True)
                time.sleep(random.uniform(1.0, 2.0))
        else:
            if an not in ani_finalizati:
                if cale_temp.exists():
                    cale_temp.unlink()
                print(f"⏭️ [Ocolit protejat] Fișierul SIMPLU {nume_pdf} a fost ocolit pentru siguranță.", flush=True)
                fisiere_esuate_protejate.append({"nume": nume_pdf, "url": url})

    if fisiere_esuate_protejate:
        print("\n⚠️ Rularea s-a încheiat. Următoarele fișiere SIMPLU au eșuat temporar și vor fi reîncercate la rularea următoare:", flush=True)
        for f in fisiere_esuate_protejate:
            print(f"  - {f['nume']}", flush=True)
            
        cale_fisier_manual = Path("liste_descarcare_manuala.txt")
        try:
            with open(cale_fisier_manual, "w", encoding="utf-8") as f_manual:
                f_manual.write("# FIȘIERE DE DESCĂRCAT MANUAL ÎN BROWSER\n")
                f_manual.write("# Copiază linkul în browser, descarcă PDF-ul și denumește-l exact ca în stânga\n\n")
                for f in fisiere_esuate_protejate:
                    f_manual.write(f"{f['nume']} -> {f['url']}\n")
            print(f"\n📝 Am generat fișierul '{cale_fisier_manual}' cu toate link-urile directe pentru descărcare manuală rapidă!", flush=True)
        except Exception as e:
            print(f"⚠️ Nu am putut genera fișierul de descărcare manuală: {e}", flush=True)
    else:
        print("\n🎉 Rularea completă s-a terminat cu succes pentru acest segment!", flush=True)

if __name__ == "__main__":
    # Suportă atât argumente din consolă (sys.argv) cât și variabilele de mediu din GitHub Actions
    if len(sys.argv) >= 3:
        an_s = int(sys.argv[1])
        an_f = int(sys.argv[2])
    else:
        an_s = START_YEAR
        an_f = END_YEAR
        
    descarca_monitoare_precalculat(an_start=an_s, am_stop=an_f)
