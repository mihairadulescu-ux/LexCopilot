import os
import json
import io
import re
from googleapiclient.http import MediaIoBaseDownload

CALE_INDEX_LOCAL = "index_xml.json"

# ID-uri de fallback
DEFAULT_TEMP_FOLDER_ID = "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"

INDEX_FILE_ID = os.getenv("XML_STORAGE_INDEX", "").strip()
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES", "").replace('"', '').replace("'", "").strip() or DEFAULT_TEMP_FOLDER_ID

# Citim folderele XML din mediu
FOLDERE_XML_RAW = os.getenv("DRIVE_FOLDER_XML", "").replace('"', '').replace("'", "").replace("\n", "").replace("\r", "")
FOLDERE_XML_IDS = [fid.strip() for fid in FOLDERE_XML_RAW.split(",") if fid.strip()] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
]


def descarca_index_master(service):
    """PASUL 1: Descărcare directă sau auto-descoperire dinamică a indexului master."""
    target_id = INDEX_FILE_ID

    # Dacă variabila lipsește sau conține ID-ul vechi, căutăm dinamic index_xml.json în folderul de metadate
    if not target_id or target_id == "1OkPgwX_F6FKwupuhD9kO3rynj4zdel0N":
        folder_meta = os.getenv("METADATA_FOLDER_ID", "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR").strip()
        try:
            query = f"'{folder_meta}' in parents and name = 'index_xml.json' and trashed = false"
            res = service.files().list(q=query, spaces='drive', fields='files(id)', supportsAllDrives=True).execute()
            files = res.get('files', [])
            if files:
                target_id = files[0]['id']
                print(f"🔍 [Index Master] Identificat dinamic pe Drive în Metadate (ID: {target_id[:8]}...)", flush=True)
        except Exception as e:
            print(f"⚠️ Căutare dinamică index eșuată: {e}", flush=True)

    if not target_id:
        print("ℹ️ 'XML_STORAGE_INDEX' nu este accesibil. Se începe cu un index vid local.", flush=True)
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}

    try:
        cerere = service.files().get_media(fileId=target_id, supportsAllDrives=True)
        fh = io.FileIO(CALE_INDEX_LOCAL, 'wb')
        downloader = MediaIoBaseDownload(fh, cerere)
        gata = False
        while not gata:
            _, gata = downloader.next_chunk()
        
        with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"📥 [Index Master] Descărcat cu succes! ({len(data.get('fisiere', {}))} fișiere în baza master)", flush=True)
            return data
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca indexul master din Drive (ID: {target_id}): {e}", flush=True)
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}


def aplica_micro_indecsi_temporari_in_memorie(service, fisiere_map):
    """
    PASUL 2: Citește și aplică micro-indecșii existenți în TEMPORARY_XML_INDEXES 
    în ordine cronologică (după createdTime), actualizând starea în memorie.
    """
    if not FOLDER_TEMP_INDEXES_ID:
        return fisiere_map

    query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
    try:
        resp = service.files().list(
            q=query, 
            fields="files(id, name, createdTime)", 
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
        ).execute()
        
        loguri_temp = resp.get('files', [])
        if not loguri_temp:
            return fisiere_map

        loguri_temp.sort(key=lambda x: x.get('createdTime', ''))

        print(f"⚡ [Index Virtual] Citire {len(loguri_temp)} micro-indecși temporari în ordine cronologică...", flush=True)

        mutații_aplicate = 0
        for log_file in loguri_temp:
            file_id = log_file['id']
            try:
                content_bytes = service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
                data_log = json.loads(content_bytes.decode('utf-8'))
                flag_updates = data_log.get('flag_updates', {})

                for nume_f, modi_flags in flag_updates.items():
                    if isinstance(modi_flags, dict):
                        if modi_flags.get("_deleted") is True:
                            if nume_f in fisiere_map:
                                del fisiere_map[nume_f]
                                mutații_aplicate += 1
                        else:
                            if nume_f in fisiere_map:
                                for key, val in modi_flags.items():
                                    fisiere_map[nume_f][key] = val
                                mutații_aplicate += 1
            except Exception:
                pass

        print(f"   └─ ✅ Aplicat în memorie {mutații_aplicate} mutații ordonate cronologic.", flush=True)

    except Exception as e:
        print(f"⚠️ Eroare la citirea micro-indecșilor temporari: {e}", flush=True)

    return fisiere_map


def obtine_index_virtual(service):
    """
    SECVENȚA EXACTĂ DE EXECUȚIE:
    1. Descarcă Master Index (index_xml.json).
    2. Citește și aplică toți micro-indecșii temporari neconsolidați.
    3. Verificarea Delta: Scanează XML-urile noi apărute pe Drive până la această secundă.
    4. Returnează Indexul Virtual.
    """
    data_master = descarca_index_master(service)
    fisiere_map = data_master.get("fisiere", {})
    last_updated = data_master.get("last_updated")

    fisiere_map = aplica_micro_indecsi_temporari_in_memorie(service, fisiere_map)

    pattern_nume = re.compile(r"brut_legislatie_(\d+)_pag(\d+)\.xml")
    noutati_gasite = 0

    if last_updated:
        for folder_id in FOLDERE_XML_IDS:
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_' and modifiedTime > '{last_updated}' and trashed = false"
            page_token = None
            
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
                    for f in files:
                        nume = f['name']
                        if nume not in fisiere_map:
                            desc = f.get('description', '')
                            match = pattern_nume.search(nume)
                            an_val = int(match.group(1)) if match else None
                            pag_val = int(match.group(2)) if match else None

                            fisiere_map[nume] = {
                                'id': f['id'],
                                'folder_id': folder_id,
                                'an': an_val,
                                'pagina': pag_val,
                                'Tags_extracted': False,
                                'processed': ('processed=true' in desc)
                            }
                            noutati_gasite += 1

                    page_token = response.get('nextPageToken', None)
                    if not page_token:
                        break
            except Exception as e:
                print(f"⚠️ Eroare verificare delta folder {folder_id[:8]}: {e}", flush=True)

    if noutati_gasite > 0:
        print(f"⚡ [Verificare Delta Finală] Identificate {noutati_gasite} fișiere XML ultra-noi apărute pe Drive.", flush=True)

    data_master["fisiere"] = fisiere_map
    data_master["total_fisiere"] = len(fisiere_map)
    return data_master


def obtine_fisiere_neprocesate(service, nume_flag="Tags_extracted"):
    index_v = obtine_index_virtual(service)
    fisiere_map = index_v.get("fisiere", {})
    
    rezultat = []
    for nume, date in fisiere_map.items():
        if not date.get(nume_flag, False):
            item = dict(date)
            item['nume'] = nume
            rezultat.append(item)

    print(f"🎯 [Filtrare Target] Găsite {len(rezultat)} fișiere neprocesate pentru '{nume_flag}'.", flush=True)
    return rezultat
