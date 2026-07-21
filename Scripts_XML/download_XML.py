import json
import os
import random
import re
import sys
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload
from lxml import etree
from zeep import Client
from zeep.plugins import HistoryPlugin
from zeep.transports import Transport

# Importăm cititorul de index virtual unificat
try:
    from XML_INDEX_READER import obtine_index_virtual
except ImportError:
    print(
        "⚠️ Nu s-a putut importa 'XML_INDEX_READER.py'. Asigură-te că fișierul există în același director."
    )
    sys.exit(1)

# ==========================================
# CULORI PENTRU CONSOLĂ
# ==========================================
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

# ==========================================
# CONFIGURĂRI DINAMICE ȘI FOLDERE FALLBACK
# ==========================================
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"
FOLDER_TEMP_INDEXES_ID = os.getenv(
    "TEMPORARY_XML_INDEXES", "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"
).strip()

DRIVE_FOLDER_RAW = os.getenv("DRIVE_FOLDER_XML", "").strip()

# Preluăm toate ID-urile de foldere din mediu sau folosim lista default de rezervă
FOLDERE_DESTINATIE = [
    f.strip() for f in DRIVE_FOLDER_RAW.replace("\n", "").split(",") if f.strip()
] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2",
]

CURRENT_FOLDER_INDEX = 0

START_YEAR = int(os.getenv("START_YEAR", "2000"))
END_YEAR = int(os.getenv("END_YEAR", "2026"))
BATCH_FLUSH_INDEX = 10  # Salvăm micro-indexul la fiecare 10 fișiere descărcate


def get_drive_service():
    """Autentifică robotul în Google Drive folosind credențialele din mediu sau fișier local."""
    scopes = ["https://www.googleapis.com/auth/drive.file"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

    if github_secret:
        print(
            f"{VERDE}🤖 [Cloud Mode] Autentificare în Google Drive folosind GitHub Secrets...{RESET}"
        )
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=scopes
        )
    else:
        print(f"{GALBEN}💻 [Local Mode] Autentificare în Google Drive...{RESET}")
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"Nu s-a găsit fișierul '{credentials_path}'!"
            )
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=scopes
        )

    return build("drive", "v3", credentials=creds)


def get_already_downloaded_pages(service, target_year):
    """Obține paginile deja existente citind Indexul Virtual (Master + Micro-indecși Temp + Delta)."""
    valid_pages = set()
    try:
        index_data = obtine_index_virtual(service)
        fisiere_map = index_data.get("fisiere", {})
        prefix = f"brut_legislatie_{target_year}_pag"

        for nume_fisier in fisiere_map.keys():
            if prefix in nume_fisier:
                match = re.search(r"_pag(\d+)\.xml$", nume_fisier)
                if match:
                    valid_pages.add(int(match.group(1)))

        print(
            f"⚡ [Index Reader] Încărcate {len(valid_pages)} pagini existente pentru anul {target_year} din Indexul Virtual."
        )
        return valid_pages
    except Exception as e:
        print(
            f"{ROSU}⚠️ Eroare la încărcarea indexului virtual: {e}. Se începe scanarea curată.{RESET}"
        )
        return set()


def upload_to_drive(service, filename, content_bytes):
    """
    Încarcă fișierul XML în Drive.
    Dacă folderul curent atinge limita de 500k fișiere (403), comută automat la următorul folder.
    """
    global CURRENT_FOLDER_INDEX

    while CURRENT_FOLDER_INDEX < len(FOLDERE_DESTINATIE):
        target_folder_id = FOLDERE_DESTINATIE[CURRENT_FOLDER_INDEX]

        try:
            file_metadata = {"name": filename, "parents": [target_folder_id]}
            media = MediaInMemoryUpload(
                content_bytes, mimetype="application/xml", resumable=True
            )

            file = (
                service.files()
                .create(
                    body=file_metadata,
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute()
            )

            file_id = file.get("id")
            print(
                f"{VERDE}✅ Fișier salvat în Drive [{CURRENT_FOLDER_INDEX + 1}/{len(FOLDERE_DESTINATIE)}]: {filename} (ID: {file_id}){RESET}"
            )
            return file_id

        except HttpError as err:
            if err.resp.status == 403 and "teamDriveFileLimitExceeded" in str(
                err
            ):
                print(
                    f"{GALBEN}⚠️ Shared Drive-ul curent ({target_folder_id[:8]}...) a atins limita de 500k fișiere!{RESET}"
                )
                CURRENT_FOLDER_INDEX += 1

                if CURRENT_FOLDER_INDEX < len(FOLDERE_DESTINATIE):
                    print(
                        f"{VERDE}🔄 Comutăm automat pe următorul folder din listă: {FOLDERE_DESTINATIE[CURRENT_FOLDER_INDEX][:8]}...{RESET}"
                    )
                else:
                    print(
                        f"{ROSU}❌ Toate folderele din listă au atins limita maximă de fișiere!{RESET}"
                    )
                    break
            else:
                print(
                    f"{ROSU}❌ Eroare HTTP Google Drive pentru {filename}: {err}{RESET}"
                )
                break

        except Exception as e:
            print(
                f"{ROSU}❌ Eroare generală upload Drive pentru {filename}: {e}{RESET}"
            )
            break

    return None


def salveaza_micro_index_temp(service, flag_updates):
    """Creează și urcă un micro-index temporar în Drive cu fișierele adăugate recent."""
    if not flag_updates:
        return True

    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    random_id = random.randint(1000, 9999)
    nume_micro_index = f"temp_index_{timestamp_str}_{random_id}.json"

    continut_payload = {
        "timestamp": timestamp_str,
        "sursa": "download_XML.py",
        "flag_updates": flag_updates,
    }

    try:
        json_bytes = json.dumps(
            continut_payload, ensure_ascii=False, indent=2
        ).encode("utf-8")
        file_metadata = {
            "name": nume_micro_index,
            "parents": [FOLDER_TEMP_INDEXES_ID],
        }
        media = MediaInMemoryUpload(
            json_bytes, mimetype="application/json", resumable=False
        )

        file = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        print(
            f"{VERDE}⚡ [Micro-Index] Înregistrat micro-index cu {len(flag_updates)} fișiere: {nume_micro_index} (ID: {file.get('id')}){RESET}",
            flush=True,
        )
        return True
    except Exception as e:
        print(
            f"{ROSU}⚠️ Eroare la salvarea micro-indexului temporar: {e}{RESET}",
            flush=True,
        )
        return False


def create_fresh_soap_client():
    """Creează o instanță curată de client SOAP (Zeep) pentru negociere WSDL."""
    history = HistoryPlugin()
    transport = Transport(timeout=90, operation_timeout=120)
    client = Client(WSDL_URL, transport=transport, plugins=[history])
    return client, history


def download_year(drive_service, composite_type_name, target_year):
    """Descarcă toate paginile lipsă pentru un singur an și salvează micro-indexul din 10 în 10 fișiere."""
    print(
        f"\n{GALBEN}{'='*70}\n📅 AN INDUSTRIAL XML: {target_year}\n{'='*70}{RESET}"
    )

    downloaded_pages = get_already_downloaded_pages(drive_service, target_year)

    pages_to_process = []
    if downloaded_pages:
        max_page = max(downloaded_pages)
        print(
            f"📦 {len(downloaded_pages)} pagini VALIDE în index pentru {target_year}. (Ultima scanată: {max_page})"
        )

        all_expected_pages = set(range(1, max_page + 1))
        gaps = sorted(list(all_expected_pages - downloaded_pages))

        if gaps:
            print(
                f"{GALBEN}🛠️ Detectat {len(gaps)} lacune în istoric: {gaps}. Începem repararea.{RESET}"
            )
            pages_to_process.extend(gaps)
        next_new_page = max_page + 1
    else:
        print("🆕 An complet nou. Începem de la pagina 1.")
        next_new_page = 1

    results_per_page = 50
    files_saved = 0
    consecutive_empty_pages = 0
    LIMITE_GOLURI_FINAL_AN = 10

    # Puffer local pentru micro-index
    mutații_micro_index = {}

    client = None
    history = None
    token_key = None

    for init_attempt in range(1, 6):
        try:
            client, history = create_fresh_soap_client()
            token_key = client.service.GetToken()
            print(f"{VERDE}🔑 Token obținut cu succes via Zeep!{RESET}")
            break
        except Exception as e:
            print(
                f"{ROSU}🚨 [Init Err] Just.ro nu răspunde (Tentativa {init_attempt}/5): {e}{RESET}"
            )
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

                client.service.Search(
                    SearchModel=search_model, tokenKey=token_key
                )

                last_response_envelope = history.last_received["envelope"]
                raw_xml_bytes = etree.tostring(
                    last_response_envelope, pretty_print=True, encoding="utf-8"
                )
                raw_xml_string = raw_xml_bytes.decode("utf-8")

                if (
                    "<a:Legi>" not in raw_xml_string
                    and "<Legi>" not in raw_xml_string
                ):
                    contor_raspunsuri_goale_curate += 1
                    if (
                        is_gap_repair
                        and contor_raspunsuri_goale_curate <= max_retries
                    ):
                        print(
                            f"{GALBEN}   ⚠️ Pagina {current_page} e goală pe server (Verificarea {contor_raspunsuri_goale_curate}/{max_retries+1}). Reîncercăm...{RESET}"
                        )
                        continue

                retry_success = True
                break
            except Exception as soap_error:
                print(
                    f"{ROSU}   ⚠️ Eroare tehnică la pagina {current_page}: {soap_error}{RESET}"
                )
                token_key = None
                a_avut_eroare_tehnica = True
                if is_gap_repair:
                    break

        if is_gap_repair and a_avut_eroare_tehnica:
            print(
                f"{ROSU}🛑 [LĂSAT LIPSA] Pagina {current_page} are probleme de rețea. O sărim acum.{RESET}"
            )
            continue

        if not retry_success and not is_gap_repair:
            consecutive_empty_pages = 0
            continue

        filename = f"brut_legislatie_{target_year}_pag{current_page}.xml"

        if (
            "<a:Legi>" not in raw_xml_string
            and "<Legi>" not in raw_xml_string
        ):
            if not is_gap_repair:
                consecutive_empty_pages += 1
                print(
                    f"{GALBEN}   ℹ️ Pagină goală detectată. Goluri consecutive: {consecutive_empty_pages}/{LIMITE_GOLURI_FINAL_AN}{RESET}"
                )
                if consecutive_empty_pages >= LIMITE_GOLURI_FINAL_AN:
                    print(
                        f"\n{VERDE}✅ Anul {target_year} finalizat (S-a confirmat capătul după {LIMITE_GOLURI_FINAL_AN} pagini goale!){RESET}"
                    )
                    break
            else:
                print(
                    f"{ROSU}🚨 [GAURĂ CONFIRMATĂ] Pagina de reparație {current_page} este definitiv goală pe server.{RESET}"
                )
                xml_martor = b"<GrupLegi><Info>PaginaGoalaConfirmataJustRo</Info></GrupLegi>"
                uploaded_id = upload_to_drive(drive_service, filename, xml_martor)
                if uploaded_id:
                    files_saved += 1
                    mutații_micro_index[filename] = {
                        "id": uploaded_id,
                        "an": target_year,
                        "pagina": current_page,
                        "Tags_extracted": False,
                    }
        else:
            if not is_gap_repair:
                consecutive_empty_pages = 0

            uploaded_id = upload_to_drive(
                drive_service, filename, raw_xml_bytes
            )
            if uploaded_id:
                files_saved += 1
                mutații_micro_index[filename] = {
                    "id": uploaded_id,
                    "an": target_year,
                    "pagina": current_page,
                    "Tags_extracted": False,
                }

        # Flush din 10 în 10 fișiere
        if len(mutații_micro_index) >= BATCH_FLUSH_INDEX:
            salveaza_micro_index_temp(drive_service, mutații_micro_index)
            mutații_micro_index.clear()

        time.sleep(1.5)

    # Flush final la ieșire din buclă
    if mutații_micro_index:
        salveaza_micro_index_temp(drive_service, mutații_micro_index)
        mutații_micro_index.clear()

    return files_saved


def download_laws_main(an_start, an_stop):
    """Funcția principală executată per segment."""
    try:
        print(
            f"{VERDE}🚀 Pornire segment industrial paralel XML. Interval: {an_start} – {an_stop}...{RESET}"
        )
        drive_service = get_drive_service()
        composite_type_name = "{http://schemas.datacontract.org/2004/07/FreeWebService}CompositeType"
        total_files_segment = 0

        for year in range(an_start, an_stop + 1):
            try:
                files_saved = download_year(
                    drive_service, composite_type_name, year
                )
                total_files_segment += files_saved
            except Exception as year_error:
                print(
                    f"{ROSU}💥 Eroare pentru anul {year}: {year_error}.{RESET}"
                )
                time.sleep(10)

        print(
            f"\n{VERDE}🎉🎉 SEGMENT XML FINALIZAT COMPLET ({an_start}-{an_stop}). Noi fișiere salvate: {total_files_segment}{RESET}"
        )
    except Exception as e:
        print(f"{ROSU}💥 Eroare critică: {str(e)}{RESET}")


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

    print(
        f"{VERDE}🎯 [Config Matrice XML] Interceptat interval din Matrix YAML: {an_s} - {an_f}{RESET}",
        flush=True,
    )
    download_laws_main(an_s, an_f)
