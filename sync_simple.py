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

def verifica_existenta_pe_server(nr, ssl_context, timeout_resilient):
    """Verifică rapid dacă un număr returnează PDF valid (True) sau 404/altceva (False)."""
    url = URL_TEMPLATE.format(numar=nr, an=AN_CURENT)
    headers = {
        "User-Agent": random.choice(USER_AGENTS), 
        "Referer": "https://monitoruloficial.ro/e-monitor/"
    }
    try:
        with httpx.Client(headers=headers, timeout=timeout_resilient, verify=ssl_context, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                if response.status_code == 200:
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "application/pdf" in content_type:
                        return True
    except Exception:
        pass
    return False

def incearca_descarcare_numar(nr, service, ssl_context, timeout_resilient, randuri_registru):
    """Descarcă efectiv numărul și îl urcă în Google Drive."""
    nume_pdf = f"MO_PI_{AN_CURENT}_{nr}.pdf"
    url = URL_TEMPLATE.format(numar=nr, an=AN_CURENT)
    cale_pdf_temp = f"temp_{nume_pdf}"
    descarcat_ok = False
    
    headers = {
        "User-Agent": random.choice(USER_AGENTS), 
        "Referer": "https://monitoruloficial.ro/e-monitor/"
    }
    
    try:
        with httpx.Client(headers=headers, timeout=timeout_resilient, verify=ssl_context, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                if response.status_code == 200:
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "application/pdf" in content_type:
                        with open(cale_pdf_temp, "wb") as f_pdf:
                            for chunk in response.iter_bytes(chunk_size=131072):
                                f_pdf.write(chunk)
                        descarcat_ok = True
                
        if descarcat_ok and os.path.exists(cale_pdf_temp) and os.path.getsize(cale_pdf_temp) > 2000:
            marime_bytes = os.path.getsize(cale_pdf_temp)
            size_kb = round(marime_bytes / 1024, 1)
            
            metadata = {'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]}
            media = MediaFileUpload(cale_pdf_temp, mimetype="application/pdf")
            nou_pdf = service.files().create(
                body=metadata, media_body=media, fields="id", supportsAllDrives=True
            ).execute()
            os.remove(cale_pdf_temp)
            
            existente_in_lista = [r for r in randuri_registru if r["numar_baza"] == str(nr)]
            if existente_in_lista:
                existente_in_lista[0].update({
                    "status": "descarcat",
                    "dimensiune_kb": str(size_kb),
                    "drive_file_id": nou_pdf["id"]
                })
            else:
                randuri_registru.append({
                    "numar_baza": str(nr),
                    "sufix": "",
                    "status": "descarcat",
                    "dimensiune_kb": str(size_kb),
                    "drive_file_id": nou_pdf["id"]
                })
            
            print(f"   {GREEN}✓ Succes ({size_kb} KB) -> ID: {nou_pdf['id']}{RESET}")
            if marime_bytes > 52428800:
                marime_mb = round(marime_bytes / 1024 / 1024, 2)
                print(f"   {YELLOW}⚠️ ATENȚIE: Fișier de dimensiune mare detectat ({marime_mb} MB)!{RESET}")
                
            return True
    except Exception as e:
        print(f"   {RED}⚠️ Eroare rețea la descărcarea numărului {nr}: {e}{RESET}")
        if os.path.exists(cale_pdf_temp):
            os.remove(cale_pdf_temp)
            
    return False

def descarca_si_salveaza_simple():
    service = obtine_drive()
    nume_registru = f"status_{AN_CURENT}.csv"
    
    query = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
    existente = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute().get("files", [])
    
    randuri_registru = []
    fisiere_descarcate = set()
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
            if row.get("status") in ["descarcat", "inexistent"] and not row.get("sufix"):
                randuri_registru_nr = row.get("numar_baza")
                if randuri_registru_nr:
                    fisiere_descarcate.add(int(randuri_registru_nr))
    
    print(f"📊 Anul {AN_CURENT}: {len(fisiere_descarcate)} numere simple mapate deja în registru.")

    timeout_resilient = httpx.Timeout(timeout=120.0, connect=20.0, read=120.0)
    ssl_context = creeaza_context_ssl_compatibil()
    download_counter = 0
    
    # ======================================================================
    # 🔍 RUTINA DE STABILIRE A CAPĂTULUI (PEAK DISCOVERY)
    # ======================================================================
    vârf_detectat = None
    punct_start = 1500
    
    print(f"🕵️ Pornește rutina de stabilire a capătului pentru anul {AN_CURENT}...")
    
    exista_la_start = verifica_existenta_pe_server(punct_start, ssl_context, timeout_resilient)
    
    if exista_la_start:
        print(f"⚠️ {YELLOW}Caz extrem: S-a detectat PDF active la {punct_start}! Căutăm limita în sus...{RESET}")
        urmatorul = punct_start
        while True:
            urmatorul += 10
            time.sleep(random.uniform(0.5, 1.0))
            print(f"   -> Verificăm la salt superior: {urmatorul}...")
            if not verifica_existenta_pe_server(urmatorul, ssl_context, timeout_resilient):
                for peak_candidate in range(urmatorul, urmatorul - 10, -1):
                    time.sleep(random.uniform(0.5, 1.0))
                    if verifica_existenta_pe_server(peak_candidate, ssl_context, timeout_resilient):
                        vârf_detectat = peak_candidate
                        break
                break
    else:
        print(f"🔍 Căutăm limita în jos de la {punct_start}...")
        for nr in range(punct_start - 10, 0, -10):
            if nr in fisiere_descarcate:
                vârf_detectat = nr
                print(f"🎯 Am intersectat registrul existent la numărul {nr}.")
                break
                
            time.sleep(random.uniform(0.5, 1.0))
            print(f"   -> Verificăm la salt inferior: {nr}...")
            if verifica_existenta_pe_server(nr, ssl_context, timeout_resilient):
                for peak_candidate in range(nr, nr + 10):
                    time.sleep(random.uniform(0.5, 1.0))
                    if not verifica_existenta_pe_server(peak_candidate, ssl_context, timeout_resilient):
                        vârf_detectat = peak_candidate - 1
                        break
                break

    if vârf_detectat is None:
        vârf_detectat = 600
        print(f"⚠️ Nu s-a putut detecta vârful. Folosim valoarea de rezervă: {vârf_detectat}")
    else:
        print(f"🎯 {GREEN}Vârf final stabilit cu succes pentru anul {AN_CURENT} la numărul: {vârf_detectat}{RESET}")

    # ======================================================================
    # 🚀 PROCEDURA PRINCIPALĂ (NUMAI ÎN JOS)
    # ======================================================================
    print(f"⏬ Începem descărcarea completă exclusiv în jos, de la {vârf_detectat} până la 1...")
    
    for nr in range(vârf_detectat, 0, -1):
        if nr in fisiere_descarcate:
            continue
            
        time.sleep(random.uniform(1.0, 2.0))
        print(f"⏳ Descarcă {nr}...")
        
        exista = incearca_descarcare_numar(nr, service, ssl_context, timeout_resilient, randuri_registru)
        if exista:
            download_counter += 1
            if download_counter % 40 == 0:
                print(f"\n{YELLOW}☕ [Pauză inteligentă] Am descărcat {download_counter} fișiere. Pauză de 5 minute (300s)...{RESET}\n")
                time.sleep(300)
        else:
            randuri_registru.append({
                "numar_baza": str(nr),
                "sufix": "",
                "status": "inexistent",
                "dimensiune_kb": "0",
                "drive_file_id": ""
            })

    # Sortare și salvare registru în Drive
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
    print(f"🚀 Registru {nume_registru} actualizat la zi în Drive!")

if __name__ == "__main__":
    descarca_si_salveaza_simple()
