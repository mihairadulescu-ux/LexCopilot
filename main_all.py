# Culori pentru un log frumos în consolă
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"


import time
import re
import json
from lxml import etree
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from zeep import Client
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin

# ==========================================
# CONFIGURĂRI ELEMENTE DE BAZĂ
# ==========================================
GOOGLE_DRIVE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

START_YEAR = 1900
END_YEAR = 2026  # Actualizat automat la anul curent din rulare


def get_drive_service():
    """Autentifică robotul în Google Drive (compatibil Local și Cloud/GitHub Actions)."""
    scopes = ["https://www.googleapis.com/auth/drive.file"]
    
    # Verificăm dacă suntem pe GitHub Actions
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        print("🤖 [Cloud Mode] Autentificare în Google Drive folosind GitHub Secrets...")
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        print("💻 [Local Mode] Autentificare în Google Drive folosind service_account.json local...")
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul de autentificare '{credentials_path}' pentru rularea locală!")
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        
    return build("drive", "v3", credentials=creds)


def get_already_downloaded_pages(service, target_year):
    """Scanează folderul Google Drive și returnează paginile deja descărcate PENTRU UN AN ANUME."""
    pages = set()
    page_token = None
    # Interogare optimizată pentru a căuta fișierele cu formatul brut specificat
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
    # Folosim timeout-uri generoase pentru a evita "Read Timeout" pe conexiunile mai slabe din cloud
    transport = Transport(timeout=90, operation_timeout=120)  
    client = Client(WSDL_URL, transport=transport, plugins=[history])
    return client, history


def download_year(drive_service, composite_type_name, target_year):
    """
    Descarcă toate paginile pentru UN singur an folosind o coadă dinamică 
    cu protecție totală împotriva erorilor de rețea.
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
            print(f"🛠️ Detectat {len(gaps)} pagini lipsă (lacune) în istoric: {gaps}. Le recuperăm primele!")
            pages_to_process.extend(gaps)
        
        # Continuăm descărcarea de la următoarea pagină nouă după cea mai mare găsită
        next_new_page = max_page + 1
    else:
        print(f"🆕 An complet nou detectat. Începem descărcarea de la pagina 1.")
        next_new_page = 1

    results_per_page = 50
    files_saved = 0
    consecutive_empty_pages = 0

    # Pasul 1: Inițializăm clientul SOAP și obținem token-ul oferit automat de API-ul Free
    client = None
    history = None
    token_key = None
    
    for init_attempt in range(1, 6):
        try:
            client, history = create_fresh_soap_client()
            token_key = client.service.GetToken()
            break
        except Exception as e:
            print(f"🚨 [Init Err] Serverul Just.ro nu răspunde pentru {target_year} (Tentativa {init_attempt}/5): {e}")
            if init_attempt == 5:
                print(f"🛑 Abandonăm temporar anul {target_year} din cauza serverului.")
                return 0
            time.sleep(30 * init_attempt)

    # Pasul 2: Procesarea paginilor din coadă
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

                # Apelul API propriu-zis
                client.service.Search(SearchModel=search_model, tokenKey=token_key)
                retry_success = True
                break
            except Exception as soap_error:
                print(f"⚠️ Eroare detectată la interogare la pagina {current_page}: {soap_error}")
                token_key = None  # Resetăm token-ul pentru a forța regenerarea lui la retry

        if not retry_success:
            print(f"🛑 Pagina {current_page} ({target_year}) a eșuat critic după toate tentativele. Trecem mai departe.")
            if not is_gap_repair:
                consecutive_empty_pages = 0
            continue

        # Pasul 3: Extragerea XML-ului brut din istoricul tranzacției SOAP
        last_response_envelope = history.last_received["envelope"]
        raw_xml_bytes = etree.tostring(last_response_envelope, pretty_print=True, encoding="utf-8")
        raw_xml_string = raw_xml_bytes.decode("utf-8")

        # Verificăm dacă pagina conține legi valide în răspuns
        if "<a:Legi>" not in raw_xml_string and "<Legi>" not in raw_xml_string:
            if not is_gap_repair:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= 2:
                    print(f"✅ Anul {target_year} finalizat complet (am primit răspunsuri goale consecutive)!")
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

        time.sleep(3.0)  # Pauză de bun-simț între apeluri ca să nu ne blocheze firewall-ul lor

    return files_saved


def download_laws_local():
    """Rulează descărcarea istorică fără întreruperi la erori globale."""
    try:
        print(f"🚀 Pornire motor industrial auto-reparabil: {START_YEAR}–{END_YEAR}...")
        drive_service = get_drive_service()
        
        # Namespace-ul corect pentru structura de date a serviciului public gratuit
        composite_type_name = "{http://schemas.datacontract.org/2004/07/FreeWebService}CompositeType"
        total_files_all_years = 0
        
        for year in range(START_YEAR, END_YEAR + 1):
            try:
                files_saved = download_year(drive_service, composite_type_name, year)
                total_files_all_years += files_saved
            except Exception as year_error:
                print(f"💥 Eroare catastrofală izolată pentru anul {year}: {year_error}. Trecem la anul următor.")
                time.sleep(60)

        print(f"\n🎉🎉 PROCES FINALIZAT. Total fișiere noi injectate în Drive: {total_files_all_years}")

    except Exception as e:
        print(f"💥 Eroare critică la inițializarea Google Drive: {str(e)}")


if __name__ == "__main__":
    download_laws_local()
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

# --- URL ORIGINAL (HTTP) ---
WSDL_URL = "http://legislatie.just.ro/api/legis/LegislatieService.svc"

# User-Agent-ul de browser folosit anterior
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

CURRENT_TOKEN = None

def obtine_token_nou():
    """Apelează serviciul public pentru a genera un token nou."""
    global CURRENT_TOKEN
    print(f"{GALBEN}[-] Se încearcă conectarea la Just.ro pentru un token nou...{RESET}", flush=True)
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ILegislatieService/GetToken",
        "User-Agent": USER_AGENT
    }
    
    soap_request = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tem="http://tempuri.org/">
       <soapenv:Header/>
       <soapenv:Body>
          <tem:GetToken/>
       </soapenv:Body>
    </soapenv:Envelope>"""
    
    try:
        response = requests.post(WSDL_URL, data=soap_request, headers=headers, timeout=15)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            namespaces = {'s': 'http://schemas.xmlsoap.org/soap/envelope/', 't': 'http://tempuri.org/'}
            token_element = root.find('.//t:GetTokenResult', namespaces)
            if token_element is not None and token_element.text:
                CURRENT_TOKEN = token_element.text
                print(f"{VERDE}[+] Token nou obținut cu succes: {CURRENT_TOKEN[:15]}...{RESET}", flush=True)
                return CURRENT_TOKEN
        print(f"{ROSU}[!] Serverul a răspuns cu codul: {response.status_code}{RESET}", flush=True)
    except Exception as e:
        print(f"{ROSU}[!] Eroare la generarea token-ului: {e}{RESET}", flush=True)
    
    return None


def executa_cerere_search(an, pagina):
    """Trimite cererea XML de căutare pentru un anumit an și pagină."""
    global CURRENT_TOKEN
    
    if not CURRENT_TOKEN:
        obtine_token_nou()
        if not CURRENT_TOKEN:
            return None
        
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ILegislatieService/Search",
        "User-Agent": USER_AGENT
    }
    
    soap_request = f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns0="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="http://schemas.microsoft.com/2003/10/Serialization/Arrays" xmlns:ns2="http://tempuri.org/">
       <SOAP-ENV:Header/>
       <ns0:Body>
          <ns2:Search>
             <ns2:SearchModel>
                <ns1:NumarPagina>{pagina}</ns1:NumarPagina>
                <ns1:RezultatePagina>100</ns1:RezultatePagina>
                <ns1:SearchAn>{an}</ns1:SearchAn>
             </ns2:SearchModel>
             <ns2:tokenKey>{CURRENT_TOKEN}</ns2:tokenKey>
          </ns2:Search>
       </ns0:Body>
    </SOAP-ENV:Envelope>"""

    try:
        response = requests.post(WSDL_URL, data=soap_request, headers=headers, timeout=15)
        return response
    except Exception as e:
        print(f"{ROSU}[!] Eroare conexiune la Search (An {an}, Pag {pagina}): {e}{RESET}", flush=True)
        return None


def ruleaza_scraping(an_start, an_end):
    global CURRENT_TOKEN
    
    for an in range(an_start, an_end + 1):
        pagina = 0
        while True:
            # --- LOGICA DE SKIP CU FORMATUL TĂU BRUT ORIGINAL ---
            nume_fisier = f"brut_legislatie_{an}_pag{pagina}.xml"
            
            if os.path.exists(nume_fisier):
                print(f"{GALBEN}[~] Pasăm peste: {nume_fisier} există deja.{RESET}", flush=True)
                pagina += 1
                continue
            
            print(f"[*] Se descarcă: Anul {an}, Pagina {pagina}...", flush=True)
            response = executa_cerere_search(an, pagina)
            
            if response is None:
                print(f"{ROSU}[!] Reîncercăm peste 10 secunde...{RESET}", flush=True)
                time.sleep(10)
                continue
                
            response_text = response.text
            
            # Auto-reparare token la expirare
            if "TOKEN INVALID" in response_text or "REGENERATI TOKEN" in response_text:
                print(f"{GALBEN}[!] Token expirat! Regenerăm...{RESET}", flush=True)
                obtine_token_nou()
                continue 
                
            if response.status_code != 200:
                print(f"{ROSU}[!] Eroare HTTP {response.status_code}. Reîncercăm...{RESET}", flush=True)
                time.sleep(5)
                continue

            # --- SALVARE CU NAMING-UL TĂU BRUT ---
            try:
                with open(nume_fisier, "w", encoding="utf-8") as f:
                    f.write(response_text)
                print(f"{VERDE}[+] Fișier salvat cu succes: {nume_fisier}{RESET}", flush=True)
            except Exception as e:
                print(f"{ROSU}[!] Eroare salvare {nume_fisier}: {e}{RESET}", flush=True)
            
            # Oprire pagină când nu mai sunt rezultate
            if "<a:TipAct>" not in response_text and "SearchResult" in response_text:
                print(f"[*] Gata cu paginile pe anul {an}.", flush=True)
                break
                
            pagina += 1
            time.sleep(1)


if __name__ == "__main__":
    ruleaza_scraping(2000, 2026)
