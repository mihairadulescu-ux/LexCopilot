import os
import sys
import json
import io
import re
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

CALE_INDEX_LOCAL = "index_xml.json"

# 1. Variabila directă cu ID-ul fișierului index_xml.json
INDEX_FILE_ID = os.getenv("XML_STORAGE_INDEX", "").strip()

# 2. Variabila pentru folderul cu indexuri temporare / mutații de flag-uri
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES", "").replace('"', '').replace("'", "").strip()

# 3. Variabila pentru folderele de stocare XML
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
        creds = service_account.Credentials.from_service_account_info(json.loads(github_secret), scopes=scopes)
    else:
        creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def descarca_index_existenta_din_drive(service):
    """Descărcare directă a indexului master prin ID-ul fix furnizat în XML_STORAGE_INDEX."""
    if os.path.exists(CALE_INDEX_LOCAL):
        return
    
    if not INDEX_FILE_ID:
        print("ℹ️ 'XML_STORAGE_INDEX' nu este setat. Se va încerca un index nou local.", flush=True)
        return

    try:
        cerere = service.files().get_media(
            fileId=INDEX_FILE_ID,
            supportsAllDrives=True
        )
        fh = io.FileIO(CALE_INDEX_LOCAL, 'wb')
        downloader = MediaIoBaseDownload(fh, cerere)
        gata = False
        while not gata:
            _, gata = downloader.next_chunk()
        print(f"📥 [Cloud Sync] Încărcat 'index_xml.json' direct din Drive (ID: {INDEX_FILE_ID[:8]}...).", flush=True)
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca fișierul index folosind XML_STORAGE_INDEX: {e}", flush=True)


def salveaza_index_in_drive(service):
    """Update direct pe fișierul de index master din Drive."""
    if not os.path.exists(CALE_INDEX_LOCAL):
        return
        
    media = MediaFileUpload(CALE_INDEX_LOCAL, mimetype='application/json', resumable=True)

    if INDEX_FILE_ID:
        try:
            service.files().update(
                fileId=INDEX_FILE_ID,
                media_body=media,
                supportsAllDrives=True
            ).execute()
            print(f"📤 [Cloud Sync] Indexul 'index_xml.json' a fost actualizat direct pe ID-ul: {INDEX_FILE_ID}!", flush=True)
            return
        except Exception as e:
            print(f"⚠️ Eroare la update pe XML_STORAGE_INDEX ({INDEX_FILE_ID}): {e}", flush=True)


def aplica_si_curata_indexuri_temporare(service, fisiere_map):
    """
    Scanează folderul TEMPORARY_XML_INDEXES, extrage doar actualizările de flag-uri,
    le aplică în indexul master și șterge fișierele temporare din Drive.
    """
    if not FOLDER_TEMP_INDEXES_ID:
        return fisiere_map

    query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
    try:
        resp = service.files().list(
            q=query, 
            fields="files(id, name)", 
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
        ).execute()
        
        loguri_temp = resp.get('files', [])
        if not loguri_temp:
            return fisiere_map

        print(f"\n{GALBEN}🔄 [Consolidare Mutații] Găsite {len(loguri_temp)} indexuri temporare în Drive. Se aplică flag-urile...{RESET}", flush=True)

        for log_file in loguri_temp:
            file_id = log_file['id']
            file_name = log_file['name']
            
            try:
                # Citim indexul temporar
                content_bytes = service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
                data_log = json.loads(content_bytes.decode('utf-8'))
                
                flag_updates = data_log.get('flag_updates', {})
                numar_updateuri = 0

                # Aplicăm STRICT modificările de flag-uri pe fișierele existente în master
                for nume_f, modi_flags in flag_updates.items():
                    if nume_f in fisiere_map and isinstance(modi_flags, dict):
                        for key, val in modi_flags.items():
                            fisiere_map[nume_f][key] = val
                        numar_updateuri += 1

                # Ștergem fișierul temporar din Drive după consumare
                service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
                print(f"   └─ ✅ Aplicat și șters din Drive: {file_name} ({numar_updateuri} fișiere actualizate cu succes)", flush=True)

            except Exception as item_err:
                print(f"   └─ ⚠️ Eroare la procesarea fișierului temporar {file_name}: {item_err}", flush=True)

    except Exception as e:
        print(f"⚠️ Eroare la parcurgerea folderului de indexuri temporare: {e}", flush=True)

    return fisiere_map


def construieste_sau_actualizeaza_index():
    service = get_drive_service()
    descarca_index_existenta_din_drive(service)
    
    pune_reset = os.getenv("STRATEGIE_RESET", "false").lower() == "true"
    
    fisiere_map = {}
    last_updated = None

    if os.path.exists(CALE_INDEX_LOCAL) and not pune_reset:
        try:
            with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
                data_stocata = json.load(f)
                if isinstance(data_stocata, dict) and "fisiere" in data_stocata:
                    last_updated = data_stocata.get("last_updated")
                    if isinstance(data_stocata["fisiere"], dict):
                        fisiere_map = data_stocata["fisiere"]
                    print(f"🧠 [Index Incremental] Încărcate {len(fisiere_map)} fișiere unice din master. Ultimul update: {last_updated}", flush=True)
        except Exception as e:
            print(f"⚠️ Eroare la citirea indexului vechi: {e}", flush=True)

    fisiere_noi_sau_modificate = 0
    pattern_nume = re.compile(r"brut_legislatie_(\d+)_pag(\d+)\.xml")

    # STEP 1: Scanăm cele 4 foldere de XML pentru a adăuga EXCLUSIV fișiere noi
    for idx_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n{GALBEN}📂 Scanare Folder XML {idx_folder}/{len(FOLDERE_XML_IDS)} (ID: {folder_id[:8]}...){RESET}", flush=True)
        
        page_token = None
        contor_folder = 0
        
        if last_updated:
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_' and modifiedTime > '{last_updated}' and trashed = false"
        else:
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_' and trashed = false"
            
        try:
            while True:
                response = service.files().list(
                    q=query,
                    spaces='drive',
                    fields='nextPageToken, files(id, name, description)',
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                files = response.get('files', [])
                if not files:
                    break

                for f in files:
                    nume = f['name']
                    desc = f.get('description', '')
                    is_processed = (desc == 'processed=true' or 'processed=true' in desc)
                    
                    match = pattern_nume.search(nume)
                    an_val = int(match.group(1)) if match else None
                    pag_val = int(match.group(2)) if match else None

                    # Dacă fișierul exista deja, îi păstrăm starea flag-urilor anterioare
                    stare_tags_existenta = fisiere_map.get(nume, {}).get("Tags_extracted", False)

                    fisiere_map[nume] = {
                        'id': f['id'],
                        'folder_id': folder_id,
                        'an': an_val,
                        'pagina': pag_val,
                        'Tags_extracted': stare_tags_existenta,
                        'processed': is_processed
                    }
                    contor_folder += 1
                    fisiere_noi_sau_modificate += 1

                    if contor_folder % 1000 == 0:
                        print(f"   ⚡ [Folder {folder_id[:8]}] Progres: {contor_folder} fișiere parcurse... (Total unice în index: {len(fisiere_map)})", flush=True)

                page_token = response.get('nextPageToken', None)
                if not page_token:
                    break
                    
            print(f"✅ [Folder Finalizat] Găsite {contor_folder} fișiere în folderul {folder_id[:8]}.", flush=True)

        except Exception as e:
            print(f"{ROSU}⚠️ Eroare scanare folder {folder_id[:8]}: {e}{RESET}", flush=True)

    # STEP 2: Aplicăm toate actualizările de flag-uri din folderul TEMPORARY_XML_INDEXES
    fisiere_map = aplica_si_curata_indexuri_temporare(service, fisiere_map)

    # STEP 3: Salvăm indexul master înapoi în Drive
    acum_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    structura_finala = {
        "last_updated": acum_iso,
        "total_fisiere": len(fisiere_map),
        "fisiere": fisiere_map
    }

    with open(CALE_INDEX_LOCAL, "w", encoding="utf-8") as f:
        json.dump(structura_finala, f, ensure_ascii=False, indent=2)

    print(f"\n{VERDE}✅ [Master Index Salvat] Total în index: {len(fisiere_map)} fișiere unice. Ștampila: {acum_iso}{RESET}", flush=True)

    salveaza_index_in_drive(service)


if __name__ == "__main__":
    construieste_sau_actualizeaza_index()
