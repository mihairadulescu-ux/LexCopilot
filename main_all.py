import os
import time
import re
import random
import datetime
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from lxml import etree
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from google.auth.transport.requests import Request
import google.auth.transport.requests
import httplib2
from zeep import Client
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin

# CONFIGURĂRI ELEMENTE DE BAZĂ REȚEAUA INDUSTRIALĂ
GOOGLE_DRIVE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

START_YEAR = 2020
END_YEAR = 2026

# Numărul de thread-uri paralele (3-4 este optim pentru a nu fi blocați de Just.ro)
MAX_WORKERS = 5 

# Lock pentru thread-safety la nivel de rețea/Drive
SESSION_LOCK = threading.Lock()
DRIVE_LOCK = threading.Lock()

# Variabile globale pentru persistența token-ului
_GLOBAL_SOAP_CLIENT = None
_GLOBAL_SOAP_HISTORY = None
_GLOBAL_TOKEN_KEY = None

_TOKEN_STATS = {
    "current_key": None,
    "created_at": None,
    "pages_processed": 0,
    "history_log": []
}


def get_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive.file"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    httplib2.Http(timeout=20)
    
    if github_secret:
        print("🤖 [Cloud Mode] Se încarcă cheia din GitHub Secrets...")
        try:
            service_account_info = json.loads(github_secret)
            creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
            custom_request = Request(google.auth.transport.requests.AuthorizedSession(creds))
            custom_request.timeout = 20
            print("🔑 [Cloud Mode] Conexiune stabilită cu succes la Google Drive API.")
            return build("drive", "v3", credentials=creds)
        except Exception as json_err:
            print(f"❌ Eroare critică la citirea cheii din GitHub Secrets: {json_err}")
            raise json_err
    else:
        print("💻 [Local Mode] Autentificare locală service_account.json...")
        credentials_path = "service_account.json"
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        return build("drive", "v3", credentials=creds)


def pre_scan_entire_drive(service):
    print("📂 [Magistrală] Se inițiază scanarea globală a folderului Google Drive...")
    database = {}
    page_token = None
    query = f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and name contains 'brut_legislatie_' and trashed = false"

    try:
        while True:
            response = service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(name)',
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()

            for file in response.get('files', []):
                name = file.get('name', '')
                match = re.search(r"brut_legislatie_(\d+)_pag(\d+)\.xml", name)
                if match:
                    an = int(match.group(1))
                    pagina = int(match.group(2))
                    if an not in database:
                        database[an] = set()
                    database[an].add(pagina)

            page_token = response.get('nextPageToken', None)
            if not page_token:
                break
        print(f"✅ Scanare completă! Am mapat istoricul pentru {len(database)} ani diferiți.")
        return database
    except Exception as e:
        print(f"⚠️ Eroare la scanarea globală ({e}). Robotul va lucra pe curat.")
        return {}


def upload_to_drive(service, filename, content_bytes):
    # Protejăm upload-ul simultan din multiple thread-uri
    with DRIVE_LOCK:
        try:
            file_metadata = {"name": filename, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
            media = MediaInMemoryUpload(content_bytes, mimetype="application/xml", resumable=True)
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            ).execute()
            print(f"✅ Salvat în Drive: {filename} (ID: {file.get('id')})")
            return True
        except Exception as e:
            print(f"❌ Eroare la upload în Drive pentru {filename}: {e}")
            return False


def print_token_health_card():
    global _TOKEN_STATS
    if not _TOKEN_STATS["current_key"]:
        return
        
    death_time = datetime.datetime.now()
    lifespan = death_time - _TOKEN_STATS["created_at"]
    
    print("\n📊" + "═"*60)
    print(f"📋 FIȘA MEDICALĂ A TOKEN-ULUI INTERN: {_TOKEN_STATS['current_key']}")
    print(f"⏱️ Creat la: {_TOKEN_STATS['created_at'].strftime('%H:%M:%S')}")
    print(f"⏳ Durată viață activă: {lifespan.seconds // 60}m {lifespan.seconds % 60}s")
    print(f"📦 Pagini procesate/salvate cu succes: {_TOKEN_STATS['pages_processed']}")
    print("═"*60 + "\n")
    
    _TOKEN_STATS["pages_processed"] = 0


def get_or_refresh_soap_session(force_refresh=False):
    global _GLOBAL_SOAP_CLIENT, _GLOBAL_SOAP_HISTORY, _GLOBAL_TOKEN_KEY, _TOKEN_STATS
    
    # Folosim Lock pentru ca thread-urile să nu ceară token-uri noi simultan
    with SESSION_LOCK:
        if _GLOBAL_SOAP_CLIENT and _GLOBAL_TOKEN_KEY and not force_refresh:
            return _GLOBAL_SOAP_CLIENT, _GLOBAL_SOAP_HISTORY, _GLOBAL_TOKEN_KEY

        if force_refresh:
            print_token_health_card()
            print("🔄 [TOKEN] ⚠️ Sesizare expirare sau refresh forțat! Se cere token nou...")
        else:
            print("🔌 [TOKEN] Inițializare sesiune la pornire robot...")

        history = HistoryPlugin()
        transport = Transport(timeout=90, operation_timeout=120)
        
        for attempt in range(1, 6):
            try:
                client = Client(WSDL_URL, transport=transport, plugins=[history])
                token = client.service.GetToken()
                if token:
                    _GLOBAL_SOAP_CLIENT = client
                    _GLOBAL_SOAP_HISTORY = history
                    _GLOBAL_TOKEN_KEY = token
                    
                    _TOKEN_STATS["current_key"] = token
                    _TOKEN_STATS["created_at"] = datetime.datetime.now()
                    
                    print(f"🔑 [TOKEN] Token NOU alocat de Just.ro: {token}")
                    return _GLOBAL_SOAP_CLIENT, _GLOBAL_SOAP_HISTORY, _GLOBAL_TOKEN_KEY
            except Exception as e:
                wait_time = 20 * attempt
                print(f"🚨 [GetToken Err] Eroare generare token (Tentativa {attempt}/5). Reîncercăm în {wait_time}s... Eroare: {e}")
                time.sleep(wait_time)
                
        raise ConnectionError("💥 Serverul Just.ro refuză complet generarea de tokenuri noi.")


def download_single_page_worker(drive_service, composite_type_name, target_year, page, is_gap_repair):
    """
    Funcție executată în paralel de thread-uri. 
    Descarcă o pagină specifică și o încarcă în Drive dacă conține date.
    """
    prefix_log = "[REPARARE]" if is_gap_repair else "[AVANS]"
    max_retries = 5
    
    for attempt in range(0, max_retries + 1):
        try:
            client, history, token_key = get_or_refresh_soap_session(force_refresh=False)

            # Mică deviație de timp între thread-uri ca să nu lovească serverul la aceeași milisecundă
            time.sleep(random.uniform(0.1, 0.8))

            composite_type = client.get_type(composite_type_name)
            search_model = composite_type(
                NumarPagina=page,
                RezultatePagina=50,
                SearchAn=str(target_year),
            )

            client.service.Search(SearchModel=search_model, tokenKey=token_key)
            
            # Preluare date primite
            last_response_envelope = history.last_received["envelope"]
            raw_xml_bytes = etree.tostring(last_response_envelope, pretty_print=True, encoding="utf-8")
            raw_xml_string = raw_xml_bytes.decode("utf-8")
            
            # Verificăm dacă pagina este goală
            if "<a:Legi>" not in raw_xml_string and "<Legi>" not in raw_xml_string:
                return {"page": page, "status": "empty", "bytes": None}
                
            # Salvare în Drive
            filename = f"brut_legislatie_{target_year}_pag{page}.xml"
            success = upload_to_drive(service=drive_service, filename=filename, content_bytes=raw_xml_bytes)
            
            if success:
                with SESSION_LOCK:
                    _TOKEN_STATS["pages_processed"] += 1
                return {"page": page, "status": "success", "bytes": raw_xml_bytes}
            else:
                return {"page": page, "status": "upload_failed", "bytes": None}

        except Exception as soap_error:
            error_str = str(soap_error).lower()
            print(f"⚠️ [Thread Err] Pagina {page} (An {target_year}): {soap_error}")
            
            if "token" in error_str or "session" in error_str or "expired" in error_str:
                get_or_refresh_soap_session(force_refresh=True)
            
            # Backoff exponențial la eroare
            if attempt < max_retries:
                time.sleep(min(60.0, 5.0 * (2 ** attempt)) + random.uniform(1.0, 3.0))
                
    return {"page": page, "status": "failed", "bytes": None}


def download_year(drive_service, composite_type_name, target_year, downloaded_pages):
    print(f"\n{'='*70}\n📅 AN INDUSTRIAL: {target_year} | MULTITHREADING ACTIV (Workers: {MAX_WORKERS})\n{'='*70}")
    
    gaps = []
    if downloaded_pages:
        max_page = max(downloaded_pages)
        print(f"📦 {len(downloaded_pages)} pagini deja în Drive pentru {target_year}. (Ultima pagină: {max_page})")
        all_expected_pages = set(range(1, max_page + 1))
        gaps = sorted(list(all_expected_pages - downloaded_pages))
        next_new_page = max_page + 1
    else:
        print(f"🆕 An gol detectat. Pornim de la pagina 1.")
        next_new_page = 1

    files_saved = 0

    # Pornim executorul de thread-uri
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        
        # ----------------- FAZA 1: REPARARE GAPS (PARALELIZATĂ COMPLET) -----------------
        if gaps:
            print(f"🛠️ Reparăm {len(gaps)} lacune în paralel...")
            futures = {
                executor.submit(download_single_page_worker, drive_service, composite_type_name, target_year, gap, True): gap 
                for gap in gaps
            }
            for future in as_completed(futures):
                res = future.result()
                if res["status"] == "success":
                    files_saved += 1
            print("✅ Faza de reparare a lacunelor s-a finalizat.")

        # ----------------- FAZA 2: AVANS (PARALELIZARE ÎN PACHETE) -----------------
        consecutive_empty_pages = 0
        
        while True:
            # Planificăm un pachet de pagini de dimensiunea MAX_WORKERS (ex: [101, 102, 103])
            pachet_pagini = []
            for i in range(MAX_WORKERS):
                pag = next_new_page
                # Verificăm instant din DB dacă cumva o avem deja (foarte rar în faza de avans, dar util ca siguranță)
                while pag in downloaded_pages:
                    print(f"☁️ [Există în Drive] brut_legislatie_{target_year}_pag{pag}.xml", flush=True)
                    pag += 1
                pachet_pagini.append(pag)
                next_new_page = pag + 1

            # Trimitem pachetul în execuție paralelă
            print(f"🚀 Se descarcă pachetul de pagini: {pachet_pagini}...", flush=True)
            futures = {
                executor.submit(download_single_page_worker, drive_service, composite_type_name, target_year, pag, False): pag
                for pag in pachet_pagini
            }
            
            # Colectăm rezultatele ordonate după numărul paginii
            rezultate_pachet = {}
            for future in as_completed(futures):
                res = future.result()
                rezultate_pachet[res["page"]] = res

            # Procesăm rezultatele în ordine crescătoare a paginilor pentru a detecta corect finalul anului
            an_terminat = False
            for pag in sorted(pachet_pagini):
                res = rezultate_pachet[pag]
                
                if res["status"] == "success":
                    files_saved += 1
                    consecutive_empty_pages = 0
                elif res["status"] == "empty":
                    consecutive_empty_pages += 1
                    print(f"ℹ️ Pagina {pag} este goală. (Contor goluri: {consecutive_empty_pages}/2)")
                    if consecutive_empty_pages >= 2:
                        print(f"🏁 [Sfârșit de An] Am detectat limitele anului {target_year} la pagina {pag}.")
                        an_terminat = True
                        break
                else:
                    # Dacă a eșuat din alte motive, nu resetăm neapărat contorul, dar logăm
                    print(f"⚠️ Pagina {pag} a finalizat cu status: {res['status']}")

            # Pauză de protecție la finalul fiecărui pachet descărcat
            time.sleep(random.uniform(2.5, 4.0))

            if an_terminat:
                break

    return files_saved


def download_laws_local():
    try:
        print(f"🚀 Pornire motor industrial optimizat de producție (MULTITHREADED)...")
        drive_service = get_drive_service()
        global_drive_db = pre_scan_entire_drive(drive_service)
        
        get_or_refresh_soap_session(force_refresh=False)
        
        composite_type_name = "{http://schemas.datacontract.org/2004/07/FreeWebService}CompositeType"
        total_files_all_years = 0
        
        for year in range(START_YEAR, END_YEAR + 1):
            try:
                downloaded_pages = global_drive_db.get(year, set())
                files_saved = download_year(drive_service, composite_type_name, year, downloaded_pages)
                total_files_all_years += files_saved
            except Exception as year_error:
                print(f"💥 Problemă izolată pe anul {year}: {year_error}.")
                time.sleep(30)

        print_token_health_card()
        print(f"\n🎉🎉 MOTOARE OPRITE SUCCESIV. Total fișiere noi adăugate: {total_files_all_years}")

    except Exception as e:
        print(f"💥 Eroare critică de magistrală: {str(e)}")


if __name__ == "__main__":
    download_laws_local()
