import os
import sys
import json
import io
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

CALE_INDEX_LOCAL = "index_xml.json"

TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")
FOLDER_IDS = [fid.strip() for fid in TARGET_FOLDERS_RAW.replace('"', '').replace("'", "").split(",") if fid.strip()] or [
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
    """Preia index_xml.json din primul folder master dacă nu există local."""
    if os.path.exists(CALE_INDEX_LOCAL):
        return
        
    id_folder_master = FOLDER_IDS[0]
    query = f"'{id_folder_master}' in parents and name = '{CALE_INDEX_LOCAL}' and trashed = false"
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
            print(f"📥 [Cloud Sync] Am descărcat indexul istoric din Google Drive.")
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca indexul din Drive: {e}")

def salveaza_index_in_drive(service):
    """Urcă sau actualizează indexul în primul folder master din Google Drive."""
    if not os.path.exists(CALE_INDEX_LOCAL):
        return
    id_folder_master = FOLDER_IDS[0]
    query = f"'{id_folder_master}' in parents and name = '{CALE_INDEX_LOCAL}' and trashed = false"
    try:
        rezultat = service.files().list(q=query, fields="files(id)").execute()
        fisiere = rezultat.get('files', [])
        media = MediaFileUpload(CALE_INDEX_LOCAL, mimetype='application/json')
        if fisiere:
            service.files().update(fileId=fisiere[0]['id'], media_body=media).execute()
            print(f"📤 [Cloud Sync] Indexul global 'index_xml.json' a fost actualizat în Drive.")
        else:
            metadata = {'name': CALE_INDEX_LOCAL, 'parents': [id_folder_master]}
            service.files().create(body=metadata, media_body=media).execute()
            print(f"📤 [Cloud Sync] Indexul 'index_xml.json' a fost creat și salvat în Drive.")
    except Exception as e:
        print(f"⚠️ Eroare la sincronizarea indexului cu Drive: {e}")

def construieste_sau_actualizeaza_index():
    service = get_drive_service()
    
    descarca_index_existenta_din_drive(service)
    pune_reset = os.getenv("STRATEGIE_RESET", "false").lower() == "true"
    
    fisiere_existente_dict = {}
    last_updated = None

    if os.path.exists(CALE_INDEX_LOCAL) and not pune_reset:
        try:
            with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
                data_stocata = json.load(f)
                if isinstance(data_stocata, dict) and "fisiere" in data_stocata:
                    last_updated = data_stocata.get("last_updated")
                    for item in data_stocata.get("fisiere", []):
                        fisiere_existente_dict[item['id']] = item
                    print(f"🧠 [Index Incremental] Încarcat index cu {len(fisiere_existente_dict)} fișiere. Ultimul update: {last_updated}")
        except Exception as e:
            print(f"⚠️ Eroare la citirea indexului vechi: {e}")

    if last_updated:
        print(f"⚡ [Mod Delta] Scanare strictă fișiere modificate/adăugate după {last_updated}...", flush=True)
    else:
        print(f"🔄 [Mod Full Scan] Scanare completă peste toate cele 4 foldere...", flush=True)

    fisiere_noi_sau_modificate = 0

    for idx_folder, folder_id in enumerate(FOLDER_IDS, start=1):
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
                    fields='nextPageToken, files(id, name, description, modifiedTime)',
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                files = response.get('files', [])
                if not files:
                    break

                for f in files:
                    desc = f.get('description', '')
                    is_processed = (desc == 'processed=true' or 'processed=true' in desc)
                    
                    item_data = {
                        'id': f['id'],
                        'name': f['name'],
                        'processed': is_processed,
                        'folder_id': folder_id
                    }
                    
                    fisiere_existente_dict[f['id']] = item_data
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
        "total_fisiere": len(fisiere_existente_dict),
        "fisiere": list(fisiere_existente_dict.values())
    }

    with open(CALE_INDEX_LOCAL, "w", encoding="utf-8") as f:
        json.dump(structura_finala, f, ensure_ascii=False, indent=2)

    print(f"\n{VERDE}✅ [Index Salvat] Total în index: {len(fisiere_existente_dict)} fișiere. Actualizări: {fisiere_noi_sau_modificate}. Ștampila: {acum_iso}{RESET}", flush=True)

    salveaza_index_in_drive(service)

if __name__ == "__main__":
    construieste_sau_actualizeaza_index()
