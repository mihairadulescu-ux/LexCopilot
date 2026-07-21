import os
import sys
import time
import json
import re
from pathlib import Path

# ==============================================================================
# CONFIGURARE CĂI DE IMPORT (PENTRU RULARE DIN GITHUB ACTIONS SAU LOCAL)
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

# Importăm configurația centralizată și cititorul de index
from drive_config import (
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

try:
    import XML_INDEX_READER
except ImportError:
    from Scripts_XML import XML_INDEX_READER

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from zeep import Client, Transport
from zeep.helpers import serialize_object

# ==============================================================================
# CONFIGURARE SERVICIU WSDL (JUST.RO) - URL OFICIAL FREEWEBSERVICE
# ==============================================================================
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"


def creeaza_client_zeep_securizat(wsdl_url, retries=5, backoff=2):
    """
    Creează un client Zeep configurat cu Session robust pe HTTP care
    include User-Agent de browser și reîncearcă automat la deconectări.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )

    strategie_retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=strategie_retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    transport = Transport(session=session, timeout=30)

    for incercare in range(1, retries + 1):
        try:
            print(
                f"🌐 Conectare la serviciul WSDL Just.ro ({wsdl_url}) (Încercarea {incercare}/{retries})...",
                flush=True,
            )
            client = Client(wsdl_url, transport=transport)
            print("✅ Conexiune WSDL stabilită cu succes!", flush=True)

            metode = [op for op in dir(client.service) if not op.startswith("_")]
            print(f"📋 Metode WSDL disponibile: {metode}", flush=True)

            return client
        except Exception as e:
            print(
                f"⚠️ Conexiunea la Just.ro a eșuat ({e}). Reîncercare în {backoff} secunde...",
                flush=True,
            )
            time.sleep(backoff)
            backoff *= 2

    print("❌ Nu s-a putut conecta la serviciul WSDL Just.ro după multiple încercări.", flush=True)
    sys.exit(1)


def autenifica_google_drive():
    """Autentificare în Google Drive API folosind Service Account din GitHub Secrets."""
    creds_json = os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY") or os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_JSON"
    )

    if not creds_json:
        print(
            "❌ [Cloud Mode] Secretul (GDRIVE_SERVICE_ACCOUNT_KEY / GOOGLE_SERVICE_ACCOUNT_JSON) nu a fost găsit!",
            flush=True,
        )
        sys.exit(1)

    try:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        print(
            f"❌ [Cloud Mode] Eroare la autentificarea în Google Drive: {e}",
            flush=True,
        )
        sys.exit(1)


def salveaza_sau_actualizeaza_in_drive(service, nume_fisier, continut_bytes, folder_id):
    """
    Salvează fișierul XML pe Google Drive în folderul specificat.
    Dacă fișierul există deja, îi actualizează conținutul.
    """
    cale_temp = f"/tmp/{nume_fisier}" if os.name != "nt" else nume_fisier
    with open(cale_temp, "wb") as f:
        f.write(continut_bytes)

    query = f"'{folder_id}' in parents and name = '{nume_fisier}' and trashed = false"

    try:
        response = (
            service.files()
            .list(**get_list_params(q=query, fields="files(id)"))
            .execute()
        )
        files = response.get("files", [])

        media = MediaFileUpload(cale_temp, mimetype="text/xml", resumable=True)

        if files:
            file_id = files[0]["id"]
            updated_file = (
                service.files()
                .update(**get_file_params(fileId=file_id, media_body=media))
                .execute()
            )
            if os.path.exists(cale_temp):
                os.remove(cale_temp)
            return updated_file.get("id")
        else:
            metadata = {"name": nume_fisier, "parents": [folder_id]}
            new_file = (
                service.files()
                .create(**get_file_params(body=metadata, media_body=media))
                .execute()
            )
            if os.path.exists(cale_temp):
                os.remove(cale_temp)
            return new_file.get("id")

    except Exception as e:
        print(
            f"❌ Eroare salvare {nume_fisier} în Drive (Folder: {folder_id[:8]}...): {e}",
            flush=True,
        )
        if os.path.exists(cale_temp):
            os.remove(cale_temp)
        return None


def genereaza_si_salveaza_micro_index(service, log_mutații):
    """Generează și salvează un micro-index temporar JSON în folderul TEMPORARY_XML_INDEXES."""
    if not log_mutații:
        return

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    nume_micro = f"temp_index_{timestamp}_{os.getpid()}.json"
    cale_temp = f"/tmp/{nume_micro}" if os.name != "nt" else nume_micro

    data_log = {"timestamp": timestamp, "flag_updates": log_mutații}

    with open(cale_temp, "w", encoding="utf-8") as f:
        json.dump(data_log, f, ensure_ascii=False, indent=2)

    folder_target = XML_INDEX_READER.FOLDER_TEMP_INDEXES_ID

    try:
        media = MediaFileUpload(cale_temp, mimetype="application/json")
        metadata = {"name": nume_micro, "parents": [folder_target]}
        res = (
            service.files()
            .create(**get_file_params(body=metadata, media_body=media))
            .execute()
        )

        print(
            f"⚡ [Micro-Index] Înregistrat micro-index cu {len(log_mutații)} fișiere: {nume_micro} (ID: {res.get('id')})",
            flush=True,
        )

    except Exception as e:
        print(f"⚠️ Eroare la salvarea micro-indexului temporar: {e}", flush=True)
    finally:
        if os.path.exists(cale_temp):
            os.remove(cale_temp)


def apeleaza_descarcare_paginata_soap(client, token, an_tinta, pagina_curenta):
    """
    Execută interogarea CĂUTARE conform DCOUMENTAȚIEI OFICIALE FreeWebService:
    Metoda: Search(SearchModel, tokenKey)
    """
    search_model = {
        "NumarPagina": pagina_curenta,
        "RezultatePagina": 50,  # Solicităm 50 rezultate per pagină
        "SearchAn": an_tinta,
        "SearchNumar": None,
        "SearchText": None,
        "SearchTitlu": None,
    }

    try:
        raspuns = client.service.Search(
            SearchModel=search_model,
            tokenKey=token
        )
        return raspuns
    except Exception as ex:
        try:
            raspuns = client.service.Search(
                searchModel=search_model,
                tokenKey=token
            )
            return raspuns
        except Exception as ex2:
            raise RuntimeError(f"Eroare la apelul Search SOAP: {ex2}")


def proceseaza_an(service, client, an_tinta, foldere_drive):
    """Descarcă paginile din API-ul Just.ro pentru anul specificat și le salvează în Drive."""
    print("=" * 70, flush=True)
    print(f"📅 AN INDUSTRIAL XML: {an_tinta}", flush=True)
    print("=" * 70, flush=True)

    index_v = XML_INDEX_READER.obtine_index_virtual(service)
    fisiere_map = index_v.get("fisiere", {})

    pagini_existente = set()
    pattern = re.compile(rf"brut_legislatie_{an_tinta}_pag(\d+)\.xml")

    for nume_f in fisiere_map.keys():
        m = pattern.search(nume_f)
        if m:
            pagini_existente.add(int(m.group(1)))

    max_pag_existenta = max(pagini_existente) if pagini_existente else 0
    print(
        f"📦 {len(pagini_existente)} pagini VALIDE în index pentru {an_tinta}. (Ultima scanată: {max_pag_existenta})",
        flush=True,
    )

    token = None
    try:
        token = client.service.GetToken()
        print("🔑 Token obținut cu succes via Zeep!", flush=True)
    except Exception as e:
        print(f"❌ Eroare la obținerea token-ului WSDL: {e}", flush=True)
        return

    pagina_curenta = max_pag_existenta + 1
    folder_idx = 0
    folder_curent_id = foldere_drive[folder_idx]

    log_mutații_sesiune = {}

    while True:
        nume_xml = f"brut_legislatie_{an_tinta}_pag{pagina_curenta}.xml"
        print(f"--- [AVANS] An {an_tinta} / Pagina {pagina_curenta} ---", flush=True)

        try:
            raspuns_soap = apeleaza_descarcare_paginata_soap(
                client, token, an_tinta, pagina_curenta
            )

            # Inspectare obiect returnat de Zeep
            dict_raspuns = serialize_object(raspuns_soap)
            
            # Verificăm dacă există lista 'Legi' în răspuns
            legi_lista = None
            if isinstance(dict_raspuns, dict):
                legi_lista = dict_raspuns.get("Legi") or dict_raspuns.get("SearchResult", {}).get("Legi")

            if not legi_lista:
                print(
                    f"🏁 Final de date detectat pentru anul {an_tinta} la pagina {pagina_curenta} (Nu mai există legi în răspuns).",
                    flush=True,
                )
                break

            # Convertim structura de date în JSON/XML lizibil
            str_json = json.dumps(dict_raspuns, ensure_ascii=False, indent=2)
            bytes_xml = str_json.encode("utf-8")

            fid = salveaza_sau_actualizeaza_in_drive(
                service, nume_xml, bytes_xml, folder_curent_id
            )

            if not fid:
                if folder_idx + 1 < len(foldere_drive):
                    folder_idx += 1
                    folder_curent_id = foldere_drive[folder_idx]
                    print(
                        f"⚠️ Shared Drive-ul curent a atins limita! Comutăm automat pe următorul folder: {folder_curent_id[:8]}...",
                        flush=True,
                    )
                    fid = salveaza_sau_actualizeaza_in_drive(
                        service, nume_xml, bytes_xml, folder_curent_id
                    )
                else:
                    print(
                        "❌ Toate folderele din lista DRIVE_FOLDER_XML sunt pline!",
                        flush=True,
                    )
                    break

            if fid:
                print(f"✅ Fișier salvat în Drive: {nume_xml} (ID: {fid})", flush=True)

                log_mutații_sesiune[nume_xml] = {
                    "id": fid,
                    "folder_id": folder_curent_id,
                    "an": an_tinta,
                    "pagina": pagina_curenta,
                    "downloaded": True,
                    "Tags_extracted": False,
                    "processed": False,
                }

            pagina_curenta += 1
            time.sleep(0.5)

        except Exception as e:
            err_str = str(e)
            
            if "token" in err_str.lower() or "invalid" in err_str.lower():
                print("🔄 Token expirat. Re-generare token...", flush=True)
                try:
                    token = client.service.GetToken()
                    continue
                except Exception as ex_t:
                    print(f"❌ Eroare re-generare token: {ex_t}", flush=True)
                    break
            else:
                print(
                    f"⚠️ Anul {an_tinta} s-a oprit la pagina {pagina_curenta}: {e}",
                    flush=True,
                )
                break

    if log_mutații_sesiune:
        genereaza_si_salveaza_micro_index(service, log_mutații_sesiune)


def main():
    print("🤖 [Cloud Mode] Autentificare în Google Drive...", flush=True)
    service = autenifica_google_drive()

    an_start = 2018
    an_end = 2026

    if len(sys.argv) >= 3:
        try:
            an_start = int(sys.argv[1])
            an_end = int(sys.argv[2])
        except ValueError:
            pass

    print(f"🎯 [Config Matrice XML] Interceptat interval: {an_start} - {an_end}", flush=True)
    print(
        f"🚀 Pornire segment industrial paralel XML. Interval: {an_start} – {an_end}...",
        flush=True,
    )

    client_zeep = creeaza_client_zeep_securizat(WSDL_URL)

    for an in range(an_start, an_end + 1):
        proceseaza_an(service, client_zeep, an, FOLDERE_XML_IDS)


if __name__ == "__main__":
    main()
