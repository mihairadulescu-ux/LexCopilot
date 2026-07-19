# Culori pentru un log frumos în consolă
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

import os
import sys
import time
import re
import json
import random
from lxml import etree
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from zeep import Client
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin

# ==========================================
# CONFIGURĂRI DINAMICE (FOLDERUL TĂU DE XML)
# ==========================================
GOOGLE_DRIVE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m" # Rămâne folderul tău din scriptul original
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

START_YEAR = int(os.getenv("START_YEAR", "2000"))
END_YEAR = int(os.getenv("END_YEAR", "2026"))


def get_drive_service():
    """Autentifică robotul în Google Drive folosind secretele din mediu."""
    scopes = ["https://www.googleapis.com/auth/drive.file"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        print(f"{VERDE}🤖 [Cloud Mode] Autentificare în Google Drive folosind GitHub Secrets...{RESET}")
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        print(f"{GALBEN}💻 [Local Mode] Autentificare în Google Drive...{RESET}")
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul '{credentials_path}'!")
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        
    return build("drive", "v3", credentials=creds)


def get_already_downloaded_pages(service, target_year):
    """
    Scanează Drive și returnează un dicționar cu paginile deja descărcate și dimensiunile lor.
    Sărim peste fișierele existente doar dacă dimensiunea lor este >= 20 bytes.
    """
    valid_pages = set()
    page_token = None
    query = f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and name contains 'brut_legislatie_{target_year}_pag' and trashed = false"

    try:
        while True:
            response = service.files().list(
                q=query, spaces='drive', fields='nextPageToken, files(name, size)',
                pageToken=page_token, supportsAllDrives=True, includeItemsFromAllDrives=True
            ).execute()

            for file in response.get('files', []):
                name = file.get('name', '')
                size = int(file.get('size', 0))
                
                if f"brut_legislatie_{target_year}_pag" not in name:
                    continue 
                
                # Regula ta de aur: dacă fișierul are mai puțin de 20 de bytes, îl considerăm lipsă și îl re-descărcăm
                if size < 20:
                    print(f"{GALBEN}   ⚠️ Re-descărcare forțată: {name} are doar {size} bytes.{RESET}")
                    continue
                
                match = re.search(r"_pag(\d+)\.xml$", name)
                if match:
                    valoare_pagina = int(match.group(1))
                    if valoare_pagina < 99999:
                        valid_pages.add(valoare_pagina)
                        
            page_token = response.get('nextPageToken', None)
            if not page_token:
                break
        return valid_pages
    except Exception as e:
        print(f"{ROSU}⚠️ Scanare Drive incompletă ({e}).{RESET}")
        return set()


def upload_to_drive(service, filename, content_bytes):
    """Încarcă fișierul XML brut în folderul din Shared Drive."""
    try:
        file_metadata = {"name": filename, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
        media = MediaInMemoryUpload(content_bytes, mimetype="application/xml", resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
        print(f"{VERDE}✅ Fișier salvat în Drive: {filename} (ID: {file.get('id')}){RESET}")
        return True
    except Exception as e:
        print(f"{ROSU}❌ Eroare upload Drive pentru {filename}: {e}{RESET}")
        return False


def create_fresh_soap_client():
    """Creează o instanță curată de client SOAP pentru a evita blocajele intermediare."""
    history = HistoryPlugin()
    transport = Transport(timeout=90, operation_timeout=120)  
    client = Client(WSDL_URL, transport=transport, plugins=[history])
    return client, history


def download_year(drive_service, composite_type_name, target_year):
    """Descarcă toate paginile lipsă sau invalide pentru un singur an."""
    print(f"\n{GALBEN}{'='*70}\n📅 AN INDUSTRIAL XML: {target_year}\n{'='*70}{RESET}")

    downloaded_pages = get_already_downloaded_pages(drive_service, target_year)
    
    pages_to_process = []
    if downloaded_pages:
        max_page = max(downloaded_pages)
        print(f"📦 {len(downloaded_pages)} pagini VALIDE în Drive pentru {target_year}. (Ultima scanată în siguranță: {max_page})")
        
        all_expected_pages = set(range(1, max_page + 1))
        gaps = sorted(list(all_expected_pages - downloaded_pages))
        
        if gaps:
            print(f"{GALBEN}🛠️ Detectat {len(gaps)} lacune/fișiere alterate în istoric: {gaps}. Începem repararea.{RESET}")
            pages_to_process.extend(gaps)
        next_new_page = max_page + 1
    else:
        print(f"🆕 An complet nou în acest segment. Începem de la pagina 1.")
        next_new_page = 1

    results_per_page = 50
    files_saved = 0
    consecutive_empty_pages = 0
    LIMITE_GOLURI_FINAL_AN = 10

    client = None
    history = None
    token_key = None
    
    for init_attempt in range(1, 6):
        try:
            client, history = create_fresh_soap_client()
            token_key = client.service.GetToken()
            break
        except Exception as e:
            print(f"{ROSU}🚨 [Init Err] Just.ro nu răspunde (Tentativa {init_attempt}/5): {e}{RESET}")
            if init_attempt == 5:
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
        a_avut_eroare_tehnica = False
        max_retries = 3
        contor_raspunsuri_goale_curate = 0

        for attempt in range(0, max_retries + 1):
            try:
                if attempt > 0:
                    time.sleep(15 * attempt)
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
                
                last_response_envelope = history.last_received["envelope"]
                raw_xml_bytes = etree.tostring(last_response_envelope, pretty_print=True, encoding="utf-8")
                raw_xml_string = raw_xml_bytes.decode("utf-8")

                if "<a:Legi>" not in raw_xml_string and "<Legi>" not in raw_xml_string:
                    contor_raspunsuri_goale_curate += 1
                    if is_gap_repair and contor_raspunsuri_goale_curate <= max_retries:
                        print(f"{GALBEN}   ⚠️ Pagina {current_page} e goală pe server (Verificarea {contor_raspunsuri_goale_curate}/{max_retries+1}). Reîncercăm...{RESET}")
                        continue
                
                retry_success = True
                break
            except Exception as soap_error:
                print(f"{ROSU}   ⚠️ Eroare tehnică la pagina {current_page}: {soap_error}{RESET}")
                token_key = None
                a_avut_eroare_tehnica = True
                if is_gap_repair:
                    break 

        if is_gap_repair and a_avut_eroare_tehnica:
            print(f"{ROSU}🛑 [LĂSAT LIPSA] Pagina {current_page} are probleme de rețea. O sărim acum.{RESET}")
            continue

        if not retry_success and not is_gap_repair:
            consecutive_empty_pages = 0
            continue

        last_response_envelope = history.last_received["envelope"]
        raw_xml_bytes = etree.tostring(last_response_envelope, pretty_print=True, encoding="utf-8")
        raw_xml_string = raw_xml_bytes.decode("utf-8")

        filename = f"brut_legislatie_{target_year}_pag{current_page}.xml"

        if "<a:Legi>" not in raw_xml_string and "<Legi>" not in raw_xml_string:
            if not is_gap_repair:
                consecutive_empty_pages += 1
                print(f"{GALBEN}   ℹ️ Pagină goală detectată. Goluri consecutive: {consecutive_empty_pages}/{LIMITE_GOLURI_FINAL_AN}{RESET}")
                if consecutive_empty_pages >= LIMITE_GOLURI_FINAL_AN:
                    print(f"\n{VERDE}✅ Anul {target_year} finalizat (S-a confirmat capătul după {LIMITE_GOLURI_FINAL_AN} pagini goale!){RESET}")
                    break
            else:
                print(f"{ROSU}🚨 [GAURĂ CONFIRMATĂ] Pagina de reparație {current_page} este definitiv goală pe server.{RESET}")
                print(f"   ✍️ Generăm fișier XML martor minimal pentru a opri scanarea repetată.")
                xml_martor = b"<GrupLegi><Info>PaginaGoalaConfirmataJustRo</Info></GrupLegi>"
                success = upload_to_drive(drive_service, filename, xml_martor)
                if success:
                    files_saved += 1
        else:
            if not is_gap_repair:
                consecutive_empty_pages = 0
                
            success = upload_to_drive(drive_service, filename, raw_xml_bytes)
            if success:
                files_saved += 1

        time.sleep(2.0)

    return files_saved


def download_laws_main(an_start, an_stop):
    """Funcția principală executată per segment."""
    try:
        print(f"{VERDE}🚀 Pornire segment industrial paralel XML. Interval: {an_start} – {an_stop}...{RESET}")
        drive_service = get_drive_service()
        composite_type_name = "{http://schemas.datacontract.org/2004/07/FreeWebService}CompositeType"
        total_files_segment = 0
        
        for year in range(an_start, an_stop + 1):
            try:
                files_saved = download_year(drive_service, composite_type_name, year)
                total_files_segment += files_saved
            except Exception as year_error:
                print(f"{ROSU}💥 Eroare pentru anul {year}: {year_error}.{RESET}")
                time.sleep(10)

        print(f"\n{VERDE}🎉🎉 SEGMENT XML FINALIZAT COMPLET ({an_start}-{an_stop}). Noi fișiere salvate: {total_files_segment}{RESET}")
    except Exception as e:
        print(f"{ROSU}💥 Eroare critică: {str(e)}{RESET}")


# ======================================================================
# PARSER ROBUST PENTRU MATRIX YAML (INTERVALE DETECTATE AUTOMAT)
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
        
    print(f"{VERDE}🎯 [Config Matrice XML] Interceptat interval din Matrix YAML: {an_s} - {an_f}{RESET}", flush=True)
    download_laws_main(an_s, an_f)
