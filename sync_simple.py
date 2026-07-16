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
    """Creează un context SSL care acceptă conexiuni vechi (util pentru anii de început ai serverului)."""
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

def curata_si_sorteaza_randuri(randuri):
    """Filtrează rândurile vide și le sortează în siguranță după numărul de bază numeric."""
    randuri_valide = []
    for r in randuri:
        if not r or not isinstance(r, dict):
            continue
        nr_str = r.get("numar_baza")
        if nr_str is not None and str(nr_str).strip() != "":
            randuri_valide.append(r)
            
    def cheie_sortare(x):
        try:
            return (int(x.get("numar_baza", 0)), x.get("sufix", ""))
        except (ValueError, TypeError):
            return (0, x.get("sufix", ""))
            
    randuri_valide.sort(key=cheie_sortare)
    return randuri_valide

def salveaza_registru_in_drive(service, file_id, nume_registru, randuri):
    """Salvează imediat starea curentă a registrului în Google Drive."""
    randuri_curatate = curata_si_sorteaza_randuri(randuri)
    
    cale_reg_scrie = f"temp_scrie_{nume_registru}"
    with open(cale_reg_scrie, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
        writer.writeheader()
        writer.writerows(randuri_curatate)
        
    media_reg = MediaFileUpload(cale_reg_scrie, mimetype="text/csv")
    
    try:
        if file_id:
            service.files().update(fileId=file_id, media_body=media_reg, supportsAllDrives=True).execute()
        else:
            metadata = {'name': nume_registru, 'parents': [TARGET_FOLDER_ID]}
            creata = service.files().create(body=metadata, media_body=media_reg, supportsAllDrives=True).execute()
            file_id = creata["id"]
    except Exception as e:
        print(f"   {RED}⚠️ Eroare la sincronizarea registrului în Drive: {e}{RESET}")
        
    if os.path.exists(cale_reg_scrie):
        os.remove(cale_reg_scrie)
        
    return file_id

def descarca_si_salveaza_simple():
    service = obtine_drive()
    nume_registru = f"status_{AN_CURENT}.csv"
    
    # 1. Căutăm registrul existent în Drive
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
            if row:
                randuri_registru.append(row)
                if row.get("status") in ["descarcat", "inexistent"] and not row.get("sufix"):
                    randuri_registru_nr = row.get("numar_baza")
                    if randuri_registru_nr:
                        fisiere_descarcate.add(int(randuri_registru_nr))
    else:
        print(f"📝 Registrul {nume_registru} nu există în Drive. Îl inițializăm acum...")
        file_id_registru = salveaza_registru_in_drive(service, None, nume_registru, [])
    
    print(f"📊 Anul {AN_CURENT}: {len(fisiere_descarcate)} numere simple mapate deja în registru.")

    timeout_resilient = httpx.Timeout(timeout=120.0, connect=20.0, read=120.0)
    ssl_context = creeaza_context_ssl_compatibil()
    
    download_counter = 0
    
    # Rulăm în ordine crescătoare
    for nr in range(1, 1201):
        if nr in fisiere_descarcate:
            continue
            
        nume_pdf = f"MO_PI_{AN_CURENT}_{nr}.pdf"
        url = URL_TEMPLATE.format(numar=nr, an=AN_CURENT)
        
        # 1 secundă pauză de siguranță
        time.sleep(1.0)
        print(f"⏳ Descarcă {nume_pdf}...")
        
        headers = {
            "User-Agent": random.choice(USER_AGENTS), 
            "Referer": "https://monitoruloficial.ro/e-monitor/"
        }
        
        try:
            cale_pdf_temp = f"temp_{nume_pdf}"
            descarcat_ok = False
            
            with httpx.Client(headers=headers, timeout=timeout_resilient, verify=ssl_context, follow_redirects=True) as client:
                with client.stream("GET", url) as response:
                    if response.status_code == 404:
                        print(f"   ✗ Numărul {nr} returnează 404 (Inexistent).")
                    else:
                        response.raise_for_status()
                        content_type = response.headers.get("Content-Type", "").lower()
                        
                        if "application/pdf" in content_type:
                            with open(cale_pdf_temp, "wb") as f_pdf:
                                for chunk in response.iter_bytes(chunk_size=131072):
                                    f_pdf.write(chunk)
                            descarcat_ok = True
                        else:
                            print(f"   ✗ Endpoint-ul a întors HTML în loc de PDF la numărul {nr.")
            
            if descarcat_ok and os.path.exists(cale_pdf_temp) and os.path.getsize(cale_pdf_temp) > 2000:
                marime_bytes = os.path.getsize(cale_pdf_temp)
                size_kb = round(marime_bytes / 1024, 1)
                
                metadata = {'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]}
                media = MediaFileUpload(cale_pdf_temp, mimetype="application/pdf")
                nou_pdf = service.files().create(
                    body=metadata, media_body=media, fields="id", supportsAllDrives=True
                ).execute()
                os.remove(cale_pdf_temp)
                
                # Actualizăm local
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
                
                # Sincronizăm instant în Google Drive
                file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                
                download_counter += 1
                if download_counter % 40 == 0:
                    print(f"\n{YELLOW}☕ [Pauză inteligentă] Am descărcat {download_counter} fișiere. Pauză de 5 minute (300s)...{RESET}\n")
                    time.sleep(300)
            else:
                if os.path.exists(cale_pdf_temp):
                    os.remove(cale_pdf_temp)
                
                # Înregistrăm în memoria locală
                randuri_registru.append({
                    "numar_baza": str(nr),
                    "sufix": "",
                    "status": "inexistent",
                    "dimensiune_kb": "0",
                    "drive_file_id": ""
                })
                
                # Sincronizăm instant în Google Drive și pentru 404
                file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                
        except Exception as e:
            print(f"   {RED}⚠️ Eroare rețea la descărcarea numărului {nr}: {e}{RESET}")
            time.sleep(5.0)

    print(f"🚀 Procesare completată pentru anul {AN_CURENT}! Toate datele sunt salvate incremental în Drive.")

if __name__ == "__main__":
    descarca_si_salveaza_simple()
