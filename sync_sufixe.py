import os
import sys
import json
import csv
import io
import time
import random
import ssl
import httpx
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Culori ANSI pentru terminal
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDER_ID = "1gRh-rWe32RNJU2PmN67XoFvkaCSotTA1"

AN_CURENT = os.getenv("AN_PROCESAT")
if not AN_CURENT:
    print(f"{RED}❌ EROARE CRITICĂ: Variabila de mediu 'AN_PROCESAT' nu este setată!{RESET}")
    sys.exit(1)

URL_TEMPLATE = "https://monitoruloficial.ro/Monitorul-Oficial--PI--{numar}--{an}.html"
SUFIXE_TEST = ["Bis", "Tris", "Quatro", "S"]

# Numărul maxim de rulări separate în care mai încercăm să descărcăm un fișier care a dat eroare de rețea
MAX_RETRIES_DISTRIBUTED = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
]

def creeaza_context_ssl_compatibil():
    context = ssl.create_default_context()
    context.options |= ssl.OP_LEGACY_SERVER_CONNECT
    context.set_ciphers('DEFAULT@SECLEVEL=1')
    return context

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError(f"{RED}❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!{RESET}")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def incearca_descarcare_sufix(nr, sfx, service, session, ssl_context, timeout_resilient, randuri_registru):
    """
    Încearcă descarcarea.
    Returnează:
      - "OK" dacă s-a descărcat cu succes.
      - "404" dacă serverul a răspuns explicit cu 404 (inexistent).
      - "ERROR" dacă a apărut o eroare de rețea/SSL (pentru retry distribuit).
    """
    numar_url = f"{nr}{sfx}"
    nume_pdf = f"MO_PI_{AN_CURENT}_{nr}{sfx}.pdf"
    url = URL_TEMPLATE.format(numar=numar_url, an=AN_CURENT)
    cale_pdf_temp = f"temp_{nume_pdf}"
    descarcat_ok = False
    status_serviciu = "404"
    
    headers = {
        "User-Agent": random.choice(USER_AGENTS), 
        "Referer": "https://monitoruloficial.ro/e-monitor/"
    }
    
    try:
        with session.stream("GET", url, headers=headers, timeout=timeout_resilient, verify=ssl_context, follow_redirects=True) as response:
            if response.status_code == 200:
                content_type = response.headers.get("Content-Type", "").lower()
                if "application/pdf" in content_type:
                    with open(cale_pdf_temp, "wb") as f_pdf:
                        for chunk in response.iter_bytes(chunk_size=131072):
                            f_pdf.write(chunk)
                    descarcat_ok = True
            elif response.status_code == 404:
                status_serviciu = "404"
                
        if descarcat_ok and os.path.exists(cale_pdf_temp) and os.path.getsize(cale_pdf_temp) > 2000:
            marime_bytes = os.path.getsize(cale_pdf_temp)
            size_kb = round(marime_bytes / 1024, 1)
            
            metadata = {'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]}
            media = MediaFileUpload(cale_pdf_temp, mimetype="application/pdf")
            nou_pdf = service.files().create(
                body=metadata, media_body=media, fields="id", supportsAllDrives=True
            ).execute()
            os.remove(cale_pdf_temp)
            
            # Actualizăm în registru
            existente_in_lista = [r for r in randuri_registru if r["numar_baza"] == str(nr) and r["sufix"] == sfx]
            if existente_in_lista:
                existente_in_lista[0].update({
                    "status": "descarcat",
                    "dimensiune_kb": str(size_kb),
                    "drive_file_id": nou_pdf["id"]
                })
            else:
                randuri_registru.append({
                    "numar_baza": str(nr),
                    "sufix": sfx,
                    "status": "descarcat",
                    "dimensiune_kb": str(size_kb),
                    "drive_file_id": nou_pdf["id"]
                })
            
            print(f"   {GREEN}🔥 [SUFIX] Găsit și descărcat: {nume_pdf} ({size_kb} KB)!{RESET}")
            if marime_bytes > 52428800:
                marime_mb = round(marime_bytes / 1024 / 1024, 2)
                print(f"   {YELLOW}⚠️ ATENȚIE: Fișier de dimensiune mare detectat ({marime_mb} MB)!{RESET}")
                
            return "OK"
            
    except Exception as e:
        print(f"   {RED}⚠️ Eroare rețea/SSL la verificarea numărului {nr}{sfx}: {e}{RESET}")
        if os.path.exists(cale_pdf_temp):
            os.remove(cale_pdf_temp)
        return "ERROR"
            
    return status_serviciu

def gestioneaza_status_esec(nr, sfx, status_curent, randuri_registru):
    """
    Calculează și actualizează în registru noul status de eșec.
    Dacă se depășește numărul maxim de încercări, marchează fișierul ca 'inexistent'.
    """
    incercare_noua = 1
    if status_curent and status_curent.startswith("esec_"):
        try:
            incercare_noua = int(status_curent.split("_")[1]) + 1
        except ValueError:
            incercare_noua = 1

    existente_in_lista = [r for r in randuri_registru if r["numar_baza"] == str(nr) and r["sufix"] == sfx]
    
    if incercare_noua > MAX_RETRIES_DISTRIBUTED:
        print(f"   ❌ [SUFIX] S-au atins cele {MAX_RETRIES_DISTRIBUTED} încercări consecutive de rețea pentru {nr}{sfx}. Marcat definitiv ca inexistent.")
        nou_status = "inexistent"
    else:
        print(f"   🕒 [SUFIX] Înregistrat eșec temporar de rețea pentru {nr}{sfx} (Încercarea {incercare_noua}/{MAX_RETRIES_DISTRIBUTED}). Va fi reîncercat la rularea următoare.")
        nou_status = f"esec_{incercare_noua}"

    if existente_in_lista:
        existente_in_lista[0].update({
            "status": nou_status,
            "dimensiune_kb": "0",
            "drive_file_id": ""
        })
    else:
        randuri_registru.append({
            "numar_baza": str(nr),
            "sufix": sfx,
            "status": nou_status,
            "dimensiune_kb": "0",
            "drive_file_id": ""
        })

def descarca_si_salveaza_sufixe():
    service = obtine_drive()
    nume_registru = f"status_{AN_CURENT}.csv"
    
    query = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
    existente = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute().get("files", [])
    
    randuri_registru = []
    statusuri_existente = {} # Harta combinatiilor (nr, sfx) -> status
    numere_baza_existente = []
    file_id_registru = None

    if existente:
        file_id_registru = existente[0]["id"]
        request = service.files().get_media(fileId=file_id_registru)
        continut_bytes = request.execute()
        
        fh = io.BytesIO(continut_bytes)
        wrapper = io.TextIOWrapper(fh, encoding='utf-8')
        reader = csv.DictReader(wrapper)
        
        for row in reader:
            randuri_registru.append(row)
            nr_baza = row.get("numar_baza")
            sfx = row.get("sufix", "")
            status = row.get("status", "")
            
            if nr_baza:
                numere_baza_existente.append(int(nr_baza))
                statusuri_existente[(int(nr_baza), sfx)] = status
    
    if numere_baza_existente:
        vârf_sufixe = max(numere_baza_existente)
    else:
        vârf_sufixe = 600
        
    print(f"📊 Anul {AN_CURENT}: {len(statusuri_existente)} combinații totale mapate în registru.")
    print(f"🎯 Vârf preluat direct din registrul simplu: {vârf_sufixe}. Rulăm ierarhic în jos.")

    timeout_resilient = httpx.Timeout(timeout=120.0, connect=20.0, read=120.0)
    ssl_context = creeaza_context_ssl_compatibil()
    download_counter = 0
    
    session = httpx.Client()
    
    for nr in range(vârf_sufixe, 0, -1):
        
        # ------------------------------------------------------------------
        # 1. Verificare SUPLIMENT (S) - complet independent
        # ------------------------------------------------------------------
        status_s = statusuri_existente.get((nr, "S"), "")
        
        # Încercăm descărcarea doar dacă nu a fost descărcat deja sau dacă nu a fost declarat definitiv inexistent
        if status_s not in ["descarcat", "inexistent"]:
            time.sleep(random.uniform(0.8, 1.5))
            print(f"⏳ Verifică sufix independent {nr}S...")
            rezultat_s = incearca_descarcare_sufix(nr, "S", service, session, ssl_context, timeout_resilient, randuri_registru)
            
            if rezultat_s == "OK":
                download_counter += 1
                if download_counter % 40 == 0:
                    print(f"\n{YELLOW}☕ [Pauză inteligentă] Am descărcat {download_counter} sufixe. Pauză de 5 minute (300s)...{RESET}\n")
                    time.sleep(300)
            elif rezultat_s == "404":
                # Dacă a întors clar 404, îl marcăm direct ca inexistent
                existente_in_lista = [r for r in randuri_registru if r["numar_baza"] == str(nr) and r["sufix"] == "S"]
                if existente_in_lista:
                    existente_in_lista[0].update({"status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})
                else:
                    randuri_registru.append({"numar_baza": str(nr), "sufix": "S", "status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})
            elif rezultat_s == "ERROR":
                # Eroare de rețea: aplicăm mecanismul de retry distribuit
                gestioneaza_status_esec(nr, "S", status_s, randuri_registru)

        # ------------------------------------------------------------------
        # 2. Lanțul Ierarhic: Bis -> Tris -> Quatro
        # ------------------------------------------------------------------
        
        # --- PASUL A: Verificăm sau determinăm starea lui 'Bis' ---
        status_bis = statusuri_existente.get((nr, "Bis"), "")
        bis_exists = False
        bis_has_network_error = False
        
        if status_bis == "descarcat":
            bis_exists = True
        elif status_bis == "inexistent":
            bis_exists = False
        else:
            # Dacă nu este nici descărcat, nici declarat inexistent (fie e nou, fie e în starea 'esec_X')
            time.sleep(random.uniform(1.0, 2.0))
            print(f"⏳ Verifică sufix {nr}Bis...")
            rezultat_bis = incearca_descarcare_sufix(nr, "Bis", service, session, ssl_context, timeout_resilient, randuri_registru)
            
            if rezultat_bis == "OK":
                bis_exists = True
                download_counter += 1
                if download_counter % 40 == 0:
                    print(f"\n{YELLOW}☕ [Pauză inteligentă] Am descărcat {download_counter} sufixe. Pauză de 5 minute (300s)...{RESET}\n")
                    time.sleep(300)
            elif rezultat_bis == "404":
                bis_exists = False
                existente_in_lista = [r for r in randuri_registru if r["numar_baza"] == str(nr) and r["sufix"] == "Bis"]
                if existente_in_lista:
                    existente_in_lista[0].update({"status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})
                else:
                    randuri_registru.append({"numar_baza": str(nr), "sufix": "Bis", "status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})
            elif rezultat_bis == "ERROR":
                bis_has_network_error = True
                gestioneaza_status_esec(nr, "Bis", status_bis, randuri_registru)

        # --- PASUL B: Verificăm sau determinăm starea lui 'Tris' (doar dacă Bis există) ---
        tris_exists = False
        tris_has_network_error = False
        
        if bis_exists:
            status_tris = statusuri_existente.get((nr, "Tris"), "")
            if status_tris == "descarcat":
                tris_exists = True
            elif status_tris == "inexistent":
                tris_exists = False
            else:
                time.sleep(random.uniform(1.0, 2.0))
                print(f"⏳ Verifică sufix {nr}Tris...")
                rezultat_tris = incearca_descarcare_sufix(nr, "Tris", service, session, ssl_context, timeout_resilient, randuri_registru)
                
                if rezultat_tris == "OK":
                    tris_exists = True
                    download_counter += 1
                    if download_counter % 40 == 0:
                        print(f"\n{YELLOW}☕ [Pauză inteligentă] Am descărcat {download_counter} sufixe. Pauză de 5 minute (300s)...{RESET}\n")
                        time.sleep(300)
                elif rezultat_tris == "404":
                    tris_exists = False
                    existente_in_lista = [r for r in randuri_registru if r["numar_baza"] == str(nr) and r["sufix"] == "Tris"]
                    if existente_in_lista:
                        existente_in_lista[0].update({"status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})
                    else:
                        randuri_registru.append({"numar_baza": str(nr), "sufix": "Tris", "status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})
                elif rezultat_tris == "ERROR":
                    tris_has_network_error = True
                    gestioneaza_status_esec(nr, "Tris", status_tris, randuri_registru)
        else:
            # Dacă Bis nu există definitiv, marcam Tris și Quatro ca inexistente (scutind cereri)
            # EXCEPȚIE: Dacă Bis a dat eroare de rețea, NU le marcăm încă ca inexistente, le lăsăm în așteptare pentru rularea următoare.
            if not bis_has_network_error:
                for sfx in ["Tris", "Quatro"]:
                    if (nr, sfx) not in statusuri_existente:
                        randuri_registru.append({"numar_baza": str(nr), "sufix": sfx, "status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})

        # --- PASUL C: Verificăm sau determinăm starea lui 'Quatro' (doar dacă Tris există) ---
        if tris_exists:
            status_quatro = statusuri_existente.get((nr, "Quatro"), "")
            if status_quatro not in ["descarcat", "inexistent"]:
                time.sleep(random.uniform(1.0, 2.0))
                print(f"⏳ Verifică sufix {nr}Quatro...")
                rezultat_quatro = incearca_descarcare_sufix(nr, "Quatro", service, session, ssl_context, timeout_resilient, randuri_registru)
                
                if resultado_quatro == "OK":
                    download_counter += 1
                    if download_counter % 40 == 0:
                        print(f"\n{YELLOW}☕ [Pauză inteligentă] Am descărcat {download_counter} sufixe. Pauză de 5 minute (300s)...{RESET}\n")
                        time.sleep(300)
                elif rezultat_quatro == "404":
                    existente_in_lista = [r for r in randuri_registru if r["numar_baza"] == str(nr) and r["sufix"] == "Quatro"]
                    if existente_in_lista:
                        existente_in_lista[0].update({"status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})
                    else:
                        randuri_registru.append({"numar_baza": str(nr), "sufix": "Quatro", "status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})
                elif rezultat_quatro == "ERROR":
                    gestioneaza_status_esec(nr, "Quatro", status_quatro, randuri_registru)
        else:
            # Dacă Tris nu există definitiv și nu a fost eroare de rețea la Tris sau Bis, marcăm Quatro ca inexistent
            if not bis_has_network_error and not tris_has_network_error:
                if (nr, "Quatro") not in statusuri_existente:
                    randuri_registru.append({"numar_baza": str(nr), "sufix": "Quatro", "status": "inexistent", "dimensiune_kb": "0", "drive_file_id": ""})

    session.close()

    # Sortare și salvare registru în Google Drive
    randuri_registru.sort(key=lambda x: (int(x["numar_baza"]), x.get("sufix", "")))
    cale_reg_scrie = f"temp_scrie_{nume_registru}"
    
    with open(cale_reg_scrie, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
        writer.writeheader()
        writer.writerows(randuri_registru)
        
    media_reg = MediaFileUpload(cale_reg_scrie, mimetype="text/csv")
    if file_id_registru:
        service.files().update(fileId=file_id_registru, media_body=media_reg, supportsAllDrives=True).execute()
    else:
        metadata = {'name': nume_registru, 'parents': [TARGET_FOLDER_ID]}
        service.files().create(body=metadata, media_body=media_reg, supportsAllDrives=True).execute()
        
    os.remove(cale_reg_scrie)
    print(f"🚀 Registru {nume_registru} actualizat cu sufixele ierarhice în Drive!")

if __name__ == "__main__":
    descarca_si_salveaza_sufixe()
