import os
import sys
import json
import time
import io
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

# Importăm cititorul de index virtual actualizat
from XML_INDEX_READER import obtine_index_virtual

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

# Folderul pentru micro-indecșii temporari
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES", "").replace('"', '').replace("'", "").strip() or "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"

# Folderele XML disponibile pentru salvare
FOLDERE_XML_RAW = os.getenv("DRIVE_FOLDER_XML", "").replace('"', '').replace("'", "").replace("\n", "").replace("\r", "")
FOLDERE_XML_IDS = [fid.strip() for fid in FOLDERE_XML_RAW.split(",") if fid.strip()] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
]


def get_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul '{credentials_path}'!")
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def salveaza_micro_index_download(service, nume_fisier, drive_file_id, folder_destinatie_id, an, pagina):
    """
    🎯 SALVARE CORECTĂ MICRO-INDEX:
    Include pașaportul tehnic complet (id, folder_id, an, pagina, downloaded, Tags_extracted).
    """
    timestamp = int(time.time())
    hash_s = hashlib.md5(f"{nume_fisier}_{timestamp}".encode()).hexdigest()[:8]
    nume_temp = f"temp_index_downloaded_{hash_s}.json"

    structura_log = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_updates": 1,
        "flag_updates": {
            nume_fisier: {
                "id": drive_file_id,
                "folder_id": folder_destinatie_id,
                "an": an,
                "pagina": pagina,
                "downloaded": True,
                "Tags_extracted": False
            }
        }
    }

    with open(nume_temp, "w", encoding="utf-8") as f:
        json.dump(structura_log, f, ensure_ascii=False, indent=2)

    try:
        media = MediaFileUpload(nume_temp, mimetype='application/json')
        file_metadata = {
            'name': nume_temp,
            'parents': [FOLDER_TEMP_INDEXES_ID]
        }
        res = service.files().create(
            body=file_metadata, 
            media_body=media, 
            supportsAllDrives=True, 
            fields='id'
        ).execute()
        print(f"✅ [MicroIndex] Logat în Drive cu ID complet ({drive_file_id[:8]}...): {nume_temp}", flush=True)
    except Exception as e:
        print(f"⚠️ Eroare logare micro-index: {e}", flush=True)
    finally:
        if os.path.exists(nume_temp):
            os.remove(nume_temp)


def obtine_folder_disponibil(service, foldere_candidate):
    """Determină primul folder din listă care nu a atins limita Drive."""
    for fid in foldere_candidate:
        try:
            # Verificăm dacă putem scrie o interogare pe folder
            query = f"'{fid}' in parents and trashed = false"
            res = service.files().list(q=query, pageSize=1, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            return fid
        except Exception:
            print(f"⚠️ [Folder Inaccesibil/Saturat] ID: {fid}. Se trece la următorul...", flush=True)
    return foldere_candidate[0] if foldere_candidate else None


def descarca_xml_pagina(an, pagina):
    """Efectuează cererea HTTP către API-ul de legislație."""
    url = f"http://legislatie.just.ro/api/getxml/{an}/{pagina}"
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            continut = response.read()
            text_str = continut.decode('utf-8', errors='ignore')
            
            # Verificăm dacă răspunsul este un XML valid și conține date
            if "<xml" in text_str.lower() or "<acte" in text_str.lower() or "<legis" in text_str.lower():
                return continut
            return None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"⚠️ HTTP Error {e.code} pe {an} pag {pagina}", flush=True)
        return None
    except Exception as e:
        print(f"⚠️ Eroare rețea descărcare {an} pag {pagina}: {e}", flush=True)
        return None


def proceseaza_segment_ani(service, an_start, an_end):
    """Procesează secvențial anii și paginile aferente."""
    index_v = obtine_index_virtual(service)
    fisiere_master = index_v.get("fisiere", {})

    foldere_active = list(FOLDERE_XML_IDS)
    folder_curent_id = obtine_folder_disponibil(service, foldere_active)

    print(f"\n{GALBEN}🚀 [START] Descărcare XML pentru anii {an_start} - {an_end}{RESET}\n", flush=True)

    for an in range(an_start, an_end + 1):
        print(f"=== AN INDUSTRIAL XML: {an} ===", flush=True)
        
        # Identificăm cea mai mare pagină deja descărcată pentru acest an
        pagini_existente = [
            info.get('pagina', 0) for nume, info in fisiere_master.items() 
            if info.get('an') == an and info.get('pagina') is not None
        ]
        
        pagina_start = max(pagini_existente) + 1 if pagini_existente else 1
        print(f"🆕 An {an}: Începem de la pagina {pagina_start}.", flush=True)

        pagina = pagina_start
        pagini_goale_consecutive = 0

        while True:
            nume_xml = f"brut_legislatie_{an}_pag{pagina}.xml"

            # Dacă pagina există deja cu ID valid în index, trecem peste
            if nume_xml in fisiere_master and fisiere_master[nume_xml].get('id'):
                pagina += 1
                pagini_goale_consecutive = 0
                continue

            print(f"--- [AVANS] An {an} / Pagina {pagina} ---", flush=True)
            continut_bytes = descarca_xml_pagina(an, pagina)

            if not continut_bytes:
                pagini_goale_consecutive += 1
                print(f"ℹ️ [Pagina Vidă] An {an} / Pagina {pagina} (consecutive: {pagini_goale_consecutive})", flush=True)
                
                # Dacă primim 3 pagini goale consecutive, considerăm că am terminat anul
                if pagini_goale_consecutive >= 3:
                    print(f"✅ Anul {an} finalizat la pagina {pagina - 3}.", flush=True)
                    break
                
                pagina += 1
                time.sleep(0.5)
                continue

            pagini_goale_consecutive = 0

            # Salvare temporară locală
            with open(nume_xml, "wb") as f:
                f.write(continut_bytes)

            # Încărcare pe Google Drive
            try:
                media = MediaFileUpload(nume_xml, mimetype='application/xml', resumable=True)
                file_metadata = {
                    'name': nume_xml,
                    'parents': [folder_curent_id]
                }
                
                res = service.files().create(
                    body=file_metadata, 
                    media_body=media, 
                    supportsAllDrives=True, 
                    fields='id'
                ).execute()
                
                real_file_id = res.get('id')
                print(f"{VERDE}✅ Fișier salvat pe Drive: {nume_xml} (ID: {real_file_id[:8]}...){RESET}", flush=True)

                # 🎯 Salvare Micro-Index cu PAȘAPORT COMPLET
                salveaza_micro_index_download(service, nume_xml, real_file_id, folder_curent_id, an, pagina)

                # Actualizăm și starea locală din memorie
                fisiere_master[nume_xml] = {
                    "id": real_file_id,
                    "folder_id": folder_curent_id,
                    "an": an,
                    "pagina": pagina,
                    "downloaded": True,
                    "Tags_extracted": False
                }

            except HttpError as err:
                # Dacă folderul e plin (500k storage limit), trecem la următorul folder
                if "numStorageBytes" in str(err) or "userRateLimitExceeded" in str(err) or err.resp.status in [403, 507]:
                    print(f"⚠️ [Folder Plin] ID: {folder_curent_id} e saturat. Îl schimbăm...", flush=True)
                    if len(foldere_active) > 1:
                        foldere_active.pop(0)
                        folder_curent_id = foldere_active[0]
                    continue
                else:
                    print(f"❌ Eroare upload Drive {nume_xml}: {err}", flush=True)
            except Exception as e:
                print(f"❌ Eroare neașteptată upload Drive {nume_xml}: {e}", flush=True)
            finally:
                if os.path.exists(nume_xml):
                    os.remove(nume_xml)

            pagina += 1
            time.sleep(0.2)


if __name__ == "__main__":
    argumente_numerice = []
    for arg in sys.argv[1:]:
        piese = arg.split()
        for piesa in piese:
            if piesa.isdigit():
                argumente_numerice.append(int(piesa))

    if len(argumente_numerice) == 1:
        an_s = an_e = argumente_numerice[0]
    elif len(argumente_numerice) >= 2:
        an_s, an_e = argumente_numerice[0], argumente_numerice[1]
    else:
        print(f"{ROSU}🛑 Eroare: Lipsesc anii ca parametru! Utilizare: python download_XML.py 1970 1974{RESET}")
        sys.exit(1)

    drive_service = get_drive_service()
    proceseaza_segment_ani(drive_service, an_s, an_e)
