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

# Șablonul URL acoperă acum atât numerele simple cât și cele cu sufix (ex: numar=12, sufix=a -> 12a)
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

def adauga_sau_updateaza_rand(randuri, nr, sufix, status, dim_kb="", d_id=""):
    gasit = False
    for idx, r in enumerate(randuri):
        if int(r["numar_baza"]) == nr and r["sufix"] == sufix:
            randuri[idx] = {"numar_baza": str(nr), "sufix": sufix, "status": status, "dimensiune_kb": dim_kb, "drive_file_id": d_id}
            gasit = True
            break
    if not gasit:
        randuri.append({"numar_baza": str(nr), "sufix": sufix, "status": status, "dimensiune_kb": dim_kb, "drive_file_id": d_id})

def proceseaza_an_faza(client, service, an, faza, drive_folder_pdf):
    print(f"\n🚀 Porniți Faza **{faza}** pentru anul {YELLOW}{an}{RESET}")
    
    nume_registru = f"status_{an}.csv"
    file_id_registru, randuri_registru = obtine_sau_creeaza_registru(service, nume_registru, drive_folder_pdf)
    
    # Determinăm statusul dinamic al anului (EoY sau nu)
    are_eoy = any(r["status"] == "EndOfYear" for r in randuri_registru)
    este_an_deschis = (not are_eoy) or (an == 2026)
    
    if are_eoy:
        print(f"ℹ️ Anul {an} este marcat istoric cu EndOfYear.")
    else:
        print(f"⚠️ Anul {an} nu are marcat EndOfYear. Va fi tratat cu reguli active (ca anul curent).")

    # Colectăm ce avem deja în cache
    deja_procesate = set()
    ultimul_numar_valid = None

    for r in randuri_registru:
        # Păstrăm identificarea pe baza combinației (numar, sufix)
        cheie = (int(r["numar_baza"]), r["sufix"])
        if r["status"] == "descarcat":
            deja_procesate.add(cheie)
            if r["sufix"] == "":
                ultimul_numar_valid = int(r["numar_baza"])
        elif r["status"] == "EndOfYear" and r["sufix"] == "":
            ultimul_numar_valid = int(r["numar_baza"])

    # Generăm lista de sufixe în funcție de Fază
    # Faza 1: doar numere simple. Faza 2: sufixe literare comune în Monitoarele Oficiale
    liste_sufixe = [""] if faza == 1 else ["a", "b", "c", "d", "bis"]
    
    download_counter = 0
    consecutive_404 = 0
    
    # Intervalul standard de scanare
    for nr in range(1, 1301):
        for sufix in liste_sufixe:
            
            if (nr, sufix) in deja_procesate:
                if sufix == "":
                    ultimul_numar_valid = nr
                continue
                
            # Dacă suntem în Faza 2 și verificăm sufixe, dar numărul de bază nu a funcționat niciodată la simple,
            # adesea nu are rost să forțăm scanarea profundă decât dacă anul e deschis.
            if faza == 2 and ultimul_numar_valid and nr > (ultimul_numar_valid + 10) and not este_an_deschis:
                break

            nume_afisare_sufix = f"_{sufix}" if sufix else ""
            nume_pdf = f"MO_PI_{an}_{nr}{nume_afisare_sufix}.pdf"
            url = URL_TEMPLATE.format(an=an, numar=nr, sufix=sufix)
            cale_pdf_temp = f"temp_{nume_pdf}"
            
            print(f"⏳ [{an} Faza {faza}] Descarcă {nume_pdf}...")
            descarcat_ok = False
            status_special = None
            
            try:
                response = client.get(url)
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "").lower()
                    if "application/pdf" in content_type:
                        with open(cale_pdf_temp, "wb") as f_pdf:
                            f_pdf.write(response.content)
                        descarcat_ok = True
                    else:
                        status_special = "404_NotFound"
                elif response.status_code == 404:
                    status_special = "404_NotFound"
                elif response.status_code in [500, 502, 503, 504]:
                    status_special = f"SERVER_ERROR_{response.status_code}"
                else:
                    status_special = f"HTTP_ERROR_{response.status_code}"
            except Exception as e:
                print(f"   {RED}⚠️ Eroare rețea: {e}{RESET}")
                status_special = "NETWORK_OVERLOAD"
                
            # --- PROTECȚIE OVERLOAD PENTRU ANI DESCHIȘI (Inclusiv istorici fără EoY) ---
            if este_an_deschis and status_special in ["NETWORK_OVERLOAD", "SERVER_ERROR_500", "SERVER_ERROR_502", "SERVER_ERROR_503", "SERVER_ERROR_504"]:
                print(f"   ⚠️ {YELLOW}[SKIP PROTECTIV]{RESET} Server suprasolicitat la {nume_pdf}. Trecem peste din browser. Reluăm la noapte.")
                time.sleep(1.5)
                continue

            # --- TRATARE SUCCES ---
            if descarcat_ok and os.path.exists(cale_pdf_temp) and os.path.getsize(cale_pdf_temp) > 2000:
                dimensiune_bytes = os.path.getsize(cale_pdf_temp)
                dimensiune_kb = f"{dimensiune_bytes / 1024:.1f}"
                
                try:
                    drive_id = incarca_pdf_in_drive(service, cale_local_pdf=cale_pdf_temp, nume_pdf=nume_pdf, drive_folder_pdf=drive_folder_pdf)
                    print(f"   {GREEN}✓ Succes ({dimensiune_kb} KB) -> ID: {drive_id}{RESET}")
                    
                    adauga_sau_updateaza_rand(randuri_registru, nr, sufix, "descarcat", dimensiune_kb, drive_id)
                    file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                    
                    if sufix == "":
                        consecutive_404 = 0
                        ultimul_numar_valid = nr
                    download_counter += 1
                except Exception as e:
                    print(f"   {RED}⚠️ Eroare Drive: {e}{RESET}")
                finally:
                    if os.path.exists(cale_pdf_temp):
                        os.remove(cale_pdf_temp)
                        
            # --- TRATARE EROARE (404) ---
            else:
                if os.path.exists(cale_pdf_temp):
                    os.remove(cale_pdf_temp)
                    
                status_salvare = status_special if status_special else "Inexistent"
                adauga_sau_updateaza_rand(randuri_registru, nr, sufix, status_salvare)
                
                # Monitorizăm golurile consecutive doar pe numerele simple (Faza 1) pentru a detecta finalul
                if faza == 1 and (status_special == "404_NotFound" or response.status_code == 200):
                    consecutive_404 += 1
                    
                if este_an_deschis:
                    # Dacă e an deschis, o frână de siguranță rezonabilă (ex: 15 goluri) previne loop-ul infinit până la 1300
                    if faza == 1 and consecutive_404 >= 15:
                        print(f"\n🛑 {YELLOW}[FRÂNĂ AN ACTIV]{RESET} 15 goluri consecutive detectate în Faza 1. Oprire etapă.")
                        file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                        return file_id_registru
                else:
                    # Regula strictă de Early Exit pentru anii istorici care aveau deja EoY sau sunt închiși la 5 goluri
                    if faza == 1 and consecutive_404 >= 5:
                        numar_marcare = ultimul_numar_valid if ultimul_numar_valid is not None else 0
                        print(f"\n🛑 {YELLOW}[EARLY EXIT HISTORIC]{RESET} 5 erori 404 consecutive.")
                        
                        for eliminat in range(nr - 4, nr + 1):
                            randuri_registru = [r for r in randuri_registru if not (int(r["numar_baza"]) == eliminat and r["sufix"] == "")]
                            
                        adauga_sau_updateaza_rand(randuri_registru, numar_marcare, "", "EndOfYear")
                        file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                        return file_id_registru
                        
                file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
            
            time.sleep(1.2)
            
            if download_counter > 0 and download_counter % 200 == 0:
                print(f"\n☕ [Pauză Antistres IP] 5 minute...")
                time.sleep(300)
                download_counter = 0
                
    return file_id_registru

def incarca_pdf_in_drive(service, cale_local_pdf, nume_pdf, drive_folder_pdf):
    metadata = {'name': nume_pdf, 'parents': [drive_folder_pdf]}
    media = MediaFileUpload(cale_local_pdf, mimetype="application/pdf", resumable=True)
    fisier_drive = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
    return fisier_drive.get("id")

def executa_sincronizare():
    # Poți pasa anii în variabila de mediu ca string separat prin virgulă, ex: "2018,2019,2024,2026"
    an_curent_raw = os.getenv("AN_CURENT")
    drive_folder_pdf = os.getenv("DRIVE_FOLDER_PDF")

    if not an_curent_raw or not drive_folder_pdf:
        print(f"{RED}❌ EROARE CRITICĂ: Variabile de mediu incomplete.{RESET}")
        sys.exit(1)
        
    # Parsăm lista de ani curată
    ani_de_procesat = [int(x.strip()) for x in an_curent_raw.split(",") if x.strip()]
    
    print(f"🌍 {GREEN}Orchestrator universal pornit pentru anii:{RESET} {ani_de_procesat}")
    service = obtine_drive()
    
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(30.0, connect=15.0)
    
    with httpx.Client(limits=limits, timeout=timeout, follow_redirects=True) as client:
        # -------------------------------------------------------------
        # FAZA 1: Rulăm mai întâi TOATE monitoarele simple pentru toți anii
        # -------------------------------------------------------------
        print(f"\n--- 🔷 FAZA 1: DESCĂRCARE MONITOARE SIMPLE ---")
        for an in ani_de_procesat:
            proceseaza_an_faza(client, service, an, faza=1, drive_folder_pdf=drive_folder_pdf)
            
        # -------------------------------------------------------------
        # FAZA 2: O luăm de la capăt cu lista de ani pentru SUFIXE
        # -------------------------------------------------------------
        print(f"\n--- 🔶 FAZA 2: EXECUTARE DETECTARE SUFIXE ---")
        for an in ani_de_procesat:
            proceseaza_an_faza(client, service, an, faza=2, drive_folder_pdf=drive_folder_pdf)

    print(f"\n🏁 {GREEN}Toate fazele s-au terminat cu succes pentru toată matricea!{RESET}")

if __name__ == "__main__":
    executa_sincronizare()
