import os
import time
import re
import datetime
import json
from lxml import etree
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from zeep import Client
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin

# CONFIGURĂRI ELEMENTE DE BAZĂ
GOOGLE_DRIVE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

START_YEAR = 1900
END_YEAR = 2026  # Anul curent conform specificațiilor curente


def get_drive_service():
    """Autentifică robotul în Google Drive (compatibil Local și Cloud/GitHub Actions)."""
    scopes = ["https://www.googleapis.com/auth/drive.file"]
    
    # Verificăm dacă suntem pe GitHub Actions (unde injectăm cheia ca variabilă de mediu)
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        print("🤖 [Cloud Mode] Autentificare în Google Drive folosind GitHub Secrets...")
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        print("💻 [Local Mode] Autentificare în Google Drive folosind service_account.json local...")
        credentials_path = "service_account.json"
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        
    return build("drive", "v3", credentials=creds)


def get_already_downloaded_pages(service, target_year):
    """Scanează folderul Google Drive și returnează paginile deja descărcate PENTRU UN AN ANUME."""
    pages = set()
    page_token = None
    query = f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and name contains 'brut_legislatie_{target_year}_pag' and trashed = false"

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
                match = re.search(r"pag(\d+)\.xml", name)
                if match:
                    pages.add(int(match.group(1)))

            page_token = response.get('nextPageToken', None)
            if not page_token:
                break

        return pages
    except Exception as e:
        print(f"⚠️ Atenție: Nu am putut scana complet folderul din Drive ({e}). Continuăm cu riscul de duplicare.")
        return set()


def upload_to_drive(service, filename, content_bytes):
    """Încarcă fișierul XML brut în folderul din Shared Drive."""
    try:
        file_metadata = {"name": filename, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
        media = MediaInMemoryUpload(content_bytes, mimetype="application/xml", resumable=True)
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        print(f"✅ Fișier salvat în Drive: {filename} (ID: {file.get('id')})")
        return True
    except Exception as e:
        print(f"❌ Eroare la upload în Drive pentru {filename}: {e}")
        return False


def create_fresh_soap_client():
    """Creează o instanță curată de client SOAP cu timeout-uri robuste extinse."""
    history = HistoryPlugin()
    # Punct critic de control: timeout inițial extins la 90 de secunde, operațiune la 120 secunde
    transport = Transport(timeout=90, operation_timeout=120)  
    client = Client(WSDL_URL, transport=transport, plugins=[history])
    return client, history


def download_year(drive_service, composite_type_name, target_year):
    """
    Descarcă toate paginile pentru UN singur an folosind o coadă dinamică 
    cu protecție totală împotriva erorilor de rețea / Read Timeout.
    """
    print(f"\n{'='*70}\n📅 AN INDUSTRIAL: {target_year}\n{'='*70}")

    downloaded_pages = get_already_downloaded_pages(drive_service, target_year)
    
    pages_to_process = []
    if downloaded_pages:
        max_page = max(downloaded_pages)
        print(f"📦 {len(downloaded_pages)} pagini găsite în Drive pentru {target_year}. (Ultima pagină: {max_page})")
        
        all_expected_pages = set(range(1, max_page + 1))
        gaps = sorted(list(all_expected_pages - downloaded_pages))
        
        if gaps:
            print(f"🛠️ Detectat {len(gaps)} lacune/pagini lipsă în istoric: {gaps}. Le reparăm primele!")
            pages_to_process.extend(gaps)
        
        next_new_page = max_page + 1
    else:
        print(f"🆕 An complet nou detectat. Începem descărcarea de la pagina 1.")
        next_new_page = 1

    results_per_page = 50
    files_saved = 0
    consecutive_empty_pages = 0

    # Inițializare client SOAP
    client = None
    history = None
    token_key = None
    
    for init_attempt in range(1, 6):
        try:
            client, history = create_fresh_soap_client()
            token_key = client.service.GetToken()
            break
        except Exception as e:
            print(f"🚨 [Init Err] Serverul Just.ro nu răspunde la inițializare pentru {target_year} (Tentativa {init_attempt}/5): {e}")
            if init_attempt == 5:
                print(f"🛑 Abandonăm anul {target_year} temporar din cauza indisponibilității serverului.")
                return 0
            time.sleep(30 * init_attempt)

    while True:
        if pages_to_process:
            current_page = pages_to_process.pop(0)
            is_gap_repair = True
        else:
            current_page = next_new_page
            next_new_page += 1
            is_gap_repair = False

        if current_page in downloaded_pages and not is_gap_repair:
            continue

        prefix_log = "[REPARARE]" if is_gap_repair else "[AVANS]"
        print(f"--- {prefix_log} An {target_year} / Pagina {current_page} ---")

        retry_success = False
        max_retries = 5

        for attempt in range(0, max_retries + 1):
            try:
                if attempt > 0:
                    wait_time = 30 * attempt
                    print(f"⏳ [Așteptare Recovery] Reîncercare {attempt}/{max_retries} peste {wait_time}s...")
                    time.sleep(wait_time)
                    
                    print("🔄 Resetare fizică client SOAP și re-autentificare preventivă...")
                    client, history = create_fresh_soap_client()
                    token_key = client.service.GetToken()

                if not token_key:
                    token_key = client.service.GetToken()

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
                print(f"⚠️ Eroare detectată la interogare la pagina {current_page}: {soap_error}")
                token_key = None  # Resetăm token-ul preventiv pentru următorul retry

        if not retry_success:
            print(f"🛑 Pagina {current_page} ({target_year}) a eșuat critic după toate tentativele. Trecem mai departe.")
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
                    print(f"✅ Anul {target_year} finalizat complet!")
                    break
            else:
                print(f"⚠️ Notă: Pagina de reparare {current_page} a întors un răspuns gol.")
        else:
            if not is_gap_repair:
                consecutive_empty_pages = 0
                
            filename = f"brut_legislatie_{target_year}_pag{current_page}.xml"
            success = upload_to_drive(drive_service, filename, raw_xml_bytes)
            if success:
                files_saved += 1

        time.sleep(3.0)  # Întârziere preventivă între pagini pentru stabilitate

    return files_saved


def download_laws_local():
    """Rulează descărcarea istorică industrială generală fără întreruperi la erori globale."""
    try:
        print(f"🚀 Pornire motor industrial auto-reparabil: {START_YEAR}–{END_YEAR}...")
        drive_service = get_drive_service()
        composite_type_name = "{http://schemas.datacontract.org/2004/07/FreeWebService}CompositeType"
        total_files_all_years = 0
        
        for year in range(START_YEAR, END_YEAR + 1):
            try:
                files_saved = download_year(drive_service, composite_type_name, year)
                total_files_all_years += files_saved
            except Exception as year_error:
                print(f"💥 Eroare catastrofală izolată pentru anul {year}: {year_error}. Trecem la anul următor.")
                time.sleep(60)

        print(f"\n🎉🎉 MOTOARE DE COLECTARE OPRITE. Total fișiere noi injectate în Drive: {total_files_all_years}")

    except Exception as e:
        print(f"💥 Eroare critică la nivelul magistralei principale de inițializare Google Drive: {str(e)}")


if __name__ == "__main__":
    download_laws_local()