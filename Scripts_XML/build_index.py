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

# 1. Variabila care deține informația cu privire la folderul de stocare metadate
FOLDER_METADATA_ID = os.getenv("DRIVE_FOLDER_METADATA", "").replace('"', '').replace("'", "").strip()

# 2. Variabila care deține informația cu privire la folderele de stocare XML-uri
FOLDERE_XML_RAW = os.getenv("DRIVE_FOLDER_XML", "").replace('"', '').replace("'", "").replace("\n", "").replace("\r", "")
FOLDERE_XML_IDS = [fid.strip() for fid in FOLDERE_XML_RAW.split(",") if fid.strip()] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
]

# Dacă folderul de metadate nu este setat separat, îl folosim pe primul din lista de XML ca fallback
if not FOLDER_METADATA_ID:
    FOLDER_METADATA_ID = FOLDERE_XML_IDS[0]

def get_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if github_secret:
        creds = service_account.Credentials.from_service_account_info(json.loads(github_secret), scopes=scopes)
    else:
        creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def descarca_index_existenta_din_drive(service):
    """Descărcăm index_xml.json strict din folderul de metadate."""
    if os.path.exists(CALE_INDEX_LOCAL):
        return
        
    query = f"'{FOLDER_METADATA_ID}' in parents and name = '{CALE_INDEX_LOCAL}' and trashed = false"
    try:
        rezultat = service.files().list(q=query, fields="files(id)").execute()
        fisiere = rezultat.get('files', [])
        if fisiere:
            cerere = service.files().get_media(fileId=fisiere[0]['id'])
            fh = io.FileIO(CALE_INDEX_LOCAL, 'wb')
            downloader = MediaIoBaseDownload(fh, cerere)
            gata = False
            while not gata:
                _, gata = downloader.next_chunk()
            print(f"📥 [Cloud Sync] Încărcat indexul din Folderul de Metadate ({FOLDER_METADATA_ID[:8]}...).")
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca indexul din Drive: {e}")

def salveaza_index_in_drive(service):
    """Salvăm/actualizăm index_xml.json în folderul de metadate."""
    if not os.path.exists(CALE_INDEX_LOCAL):
        return
    
    query = f"'{FOLDER_METADATA_ID}' in parents and name = '{CALE_INDEX_LOCAL}' and trashed = false"
    try:
        rezultat = service.files().list(q=query, fields="files(id)").execute()
        fisiere = rezultat.get('files', [])
        media = MediaFileUpload(CALE_INDEX_LOCAL, mimetype='application/json')
        if fisiere:
            service.files().update(fileId=fisiere[0]['id'], media_body=media).execute()
            print(f"📤 [Cloud Sync] Indexul 'index_xml.json' a fost actualizat în Folderul de Metadate!")
        else:
            metadata = {'name': CALE_INDEX_LOCAL, 'parents': [FOLDER_METADATA_ID]}
            service.files().create(body=metadata, media_body=media).execute()
            print(f"📤 [Cloud Sync] Indexul 'index_xml.json' a fost creat în Folderul de Metadate!")
    except Exception as e:
        print(f"⚠️ Eroare la sincronizarea indexului cu Drive: {e}")

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
                    print(f"🧠 [Index Incremental] Încărcate {len(fisiere_map)} fișiere. Ultimul update: {last_updated}")
        except Exception as e:
            print(f"⚠️ Eroare la citirea indexului vechi: {e}")

    fisiere_noi_sau_modificate = 0
    pattern_nume = re.compile(r"brut_legislatie_(\d+)_pag(\d+)\.xml")

    for idx_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
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

                page_token = response.get('nextPageToken', None)
                if not page_token:
                    break
                    
            if contor_folder > 0:
                print(f"   ➕ [{folder_id[:8]}] Detectate {contor_folder} actualizări.", flush=True)

        except Exception as e:
            print(f"{ROSU}⚠️ Eroare scanare folder {folder_id[:8]}: {e}{RESET}", flush=True)

    acum_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    structura_finala = {
        "last_updated": acum_iso,
        "total_fisiere": len(fisiere_map),
        "fisiere": fisiere_map
    }

    with open(CALE_INDEX_LOCAL, "w", encoding="utf-8") as f:
        json.dump(structura_finala, f, ensure_ascii=False, indent=2)

    print(f"\n{VERDE}✅ [Index Salvat] Total în index: {len(fisiere_map)} fișiere. Actualizări: {fisiere_noi_sau_modificate}. Ștampila: {acum_iso}{RESET}", flush=True)

    salveaza_index_in_drive(service)

if __name__ == "__main__":
    construieste_sau_actualizeaza_index()
