import os
import time
import re
import random
import datetime
import json
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
END_YEAR = 2023

# Variabile globale pentru persistența token-ului
_GLOBAL_SOAP_CLIENT = None
_GLOBAL_SOAP_HISTORY = None
_GLOBAL_TOKEN_KEY = None

# METRICI DE TELEMETRIE PENTRU FIȘA MEDICALĂ A TOKEN-ULUI
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
    """Printează fișa medicală a token-ului retras din activitate."""
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
    
    # Resetăm contorul pentru următorul token
    _TOKEN_STATS["pages_processed"] = 0


def get_or_refresh_soap_session(force_refresh=False):
    global _GLOBAL_SOAP_CLIENT, _GLOBAL_SOAP_HISTORY, _GLOBAL_TOKEN_KEY, _TOKEN_STATS
    
    if _GLOBAL_SOAP_CLIENT and _GLOBAL_TOKEN_KEY and not force_refresh:
        return _GLOBAL_SOAP_CLIENT, _GLOBAL_SOAP_HISTORY, _GLOBAL_TOKEN_KEY

    if force_refresh:
        # Înainte de a-l distruge, îi facem raportul medical celui vechi
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
                
                # Înregistrăm noul pacient în tabelul de telemetrie
                _TOKEN_STATS["current_key"] = token
                _TOKEN_STATS["created_at"] = datetime.datetime.now()
                
                print(f"🔑 [TOKEN] Token NOU alocat de Just.ro: {token}")
                return _GLOBAL_SOAP_CLIENT, _GLOBAL_SOAP_HISTORY, _GLOBAL_TOKEN_KEY
        except Exception as e:
            wait_time = 20 * attempt
            print(f"🚨 [GetToken Err] Eroare generare token (Tentativa {attempt}/5). Reîncercăm în {wait_time}s... Eroare: {e}")
            time.sleep(wait_time)
            
    raise ConnectionError("💥 Serverul Just.ro refuză complet generarea de tokenuri noi.")


def download_year(drive_service, composite_type_name, target_year, downloaded_pages):
    global _TOKEN_STATS
    print(f"\n{'='*70}\n📅 AN INDUSTRIAL: {target_year}\n{'='*70}")
    
    pages_to_process = []
    if downloaded_pages:
        max_page = max(downloaded_pages)
        print(f"📦 {len(downloaded_pages)} pagini deja în Drive pentru {target_year}. (Ultima pagină: {max_page})")
        all_expected_pages = set(range(1, max_page + 1))
        gaps = sorted(list(all_expected_pages - downloaded_pages))
        if gaps:
            print(f"🛠️ Detectat {len(gaps)} lacune în istoric: {gaps}. Le reparăm.")
            pages_to_process.extend(gaps)
        next_new_page = max_page + 1
    else:
        print(f"🆕 An gol detectat. Pornim de la pagina 1.")
        next_new_page = 1

    results_per_page = 50
    files_saved = 0
    consecutive_empty_pages = 0

    while True:
        # 1. Determinăm pagina curentă pe care o evaluăm
        if pages_to_process:
            current_page = pages_to_process[0]  # Doar ne uităm la ea, o scoatem din listă doar dacă o procesăm real
            is_gap_repair = True
        else:
            current_page = next_new_page
            is_gap_repair = False

        # --- OPTIMIZARE EXTREMĂ: Skip instantaneu fără sleep/pauze de rețea ---
        if current_page in downloaded_pages and not is_gap_repair:
            print(f"☁️ [Există în Drive] brut_legislatie_{target_year}_pag{current_page}.xml", flush=True)
            next_new_page += 1
            continue  # Trecem instant la următoarea pagină, fără delay-uri!

        # Dacă am trecut de filtrul de mai sus, înseamnă că pagină NU este în Drive și trebuie descărcată.
        # Acum o putem elimina din coada de reparare gaps.
        if is_gap_repair:
            pages_to_process.pop(0)
        else:
            next_new_page += 1

        prefix_log = "[REPARARE]" if is_gap_repair else "[AVANS]"
        retry_success = False
        max_retries = 5
        
        for attempt in range(0, max_retries + 1):
            try:
                # Accesăm serverul SOAP Just.ro doar pentru fișiere cu adevărat noi!
                client, history, token_key = get_or_refresh_soap_session(force_refresh=False)

                print(f"--- {prefix_log} An {target_year} / Pagina {current_page} | Token activ: {token_key[:12]}... (Încercare {attempt}/{max_retries}) ---")

                if attempt > 0:
                    base_wait = 10.0
                    max_wait = 180.0
                    wait_time = min(max_wait, base_wait * (2 ** attempt)) + random.uniform(0.0, 5.0)
                    print(f"⏳ [Backoff] Reîncercare în {wait_time:.2f} secunde...")
                    time.sleep(wait_time)

                composite_type = client.get_type(composite_type_name)
                search_model = composite_type(
                    NumarPagina=current_page,
                    RezultatePagina=results_per_page,
                    SearchAn=str(target_year),
                )

                client.service.Search(SearchModel=search_model, tokenKey=token_key)
                retry_success = True
                break
            except Exception as soap_error:
                error_str = str(soap_error).lower()
                print(f"⚠️ [Search Err] Eroare la Search() pe pagina {current_page}: {soap_error}")
                
                if "504" in error_str or "502" in error_str or "timed out" in error_str or "timeout" in error_str:
                    print("🌐 [Diagnostic] Eroare infrastructurală (Nginx/Timeout). Tokenul rămâne intact.")
                elif "token" in error_str or "session" in error_str or "expired" in error_str:
                    print("🔑 [Diagnostic] Confirmare expirare token! Forțăm reîmprospătarea...")
                    get_or_refresh_soap_session(force_refresh=True)

        if not retry_success:
            print(f"🛑 Pagina {current_page} ({target_year}) s-a blocat definitiv. O sărim.")
            if not is_gap_repair:
                consecutive_empty_pages = 0
            continue

        last_response_envelope = history.last_received["envelope"]
        raw_xml_bytes = etree.tostring(last_response_envelope, pretty_print=True, encoding="utf-8")
        raw_xml_string = raw_xml_bytes.decode("utf-8")

        if "<a:Legi>" not in raw_xml_string and "<Legi>" not in raw_xml_string:
            if not is_gap_repair:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= 2:
                    print(f"✅ Anul {target_year} terminat în siguranță!")
                    break
            else:
                print(f"⚠️ Pagina {current_page} nu a întors date.")
        else:
            if not is_gap_repair:
                consecutive_empty_pages = 0
                
            filename = f"brut_legislatie_{target_year}_pag{current_page}.xml"
            success = upload_to_drive(service=drive_service, filename=filename, content_bytes=raw_xml_bytes)
            if success:
                files_saved += 1
                _TOKEN_STATS["pages_processed"] += 1

        # Această pauză protejează serverul Just.ro și se execută DOAR când am făcut descărcare reală!
        time.sleep(random.uniform(3.0, 5.0))

    return files_saved


def download_laws_local():
    try:
        print(f"🚀 Pornire motor industrial optimizat de producție...")
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

        # La final de tot, printăm stadiul ultimului token folosit
        print_token_health_card()
        print(f"\n🎉🎉 MOTOARE OPRITE SUCCESIV. Total fișiere noi adăugate: {total_files_all_years}")

    except Exception as e:
        print(f"💥 Eroare critică de magistrală: {str(e)}")


if __name__ == "__main__":
    download_laws_local()
