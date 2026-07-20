# ==============================================================================
# 📌 CUM SE APELEAZĂ DIN ALTE SCRIPTURI (QUICK REFERENCE):
#
# from index_reader import obtine_index_virtual, obtine_fisiere_neprocesate
# 
# # Opțiunea A: Obții dicționarul complet actualizat la secundă
# index_virtual = obtine_index_virtual(service)
# 
# # Opțiunea B: Obții direct lista de fișiere neprocesate pentru un flag (ex: 'Tags_extracted')
# de_procesat = obtine_fisiere_neprocesate(service, nume_flag="Tags_extracted")
# ==============================================================================

import os
import json
import io
import re
from googleapiclient.http import MediaIoBaseDownload

CALE_INDEX_LOCAL = "index_xml.json"
INDEX_FILE_ID = os.getenv("XML_STORAGE_INDEX", "").strip()
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES", "").replace('"', '').replace("'", "").strip()

# Citim folderele XML din mediu
FOLDERE_XML_RAW = os.getenv("DRIVE_FOLDER_XML", "").replace('"', '').replace("'", "").replace("\n", "").replace("\r", "")
FOLDERE_XML_IDS = [fid.strip() for fid in FOLDERE_XML_RAW.split(",") if fid.strip()] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
]


def descarca_index_master(service):
    """Descărcare ultra-rapidă directă prin ID-ul fix furnizat în XML_STORAGE_INDEX."""
    if not INDEX_FILE_ID:
        print("ℹ️ 'XML_STORAGE_INDEX' nu este setat. Se începe cu un index vid local.", flush=True)
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}

    try:
        cerere = service.files().get_media(fileId=INDEX_FILE_ID, supportsAllDrives=True)
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
        print(f"⚠️ Nu s-a putut descărca indexul master din Drive: {e}", flush=True)
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}


def aplica_micro_indecsi_temporari_in_memorie(service, fisiere_map):
    """
    CITEȘTE și aplică micro-indecșii existenți în TEMPORARY_XML_INDEXES 
    ÎN ORDINE CRONOLOGICĂ (după createdTime), actualizând starea în memorie.
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

        # 🕒 SORTARE CRONOLOGICĂ EXPLICITĂ (de la cel mai vechi la cel mai nou)
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
                        # Dacă e marcat ca șters, îl scoatem din indexul virtual
                        if modi_flags.get("_deleted") is True:
                            if nume_f in fisiere_map:
                                del fisiere_map[nume_f]
                                mutații_aplicate += 1
                        else:
                            # Altfel actualizăm/suprascriem flag-urile în ordine cronologică
                            if nume_f in fisiere_map:
                                for key, val in modi_flags.items():
                                    fisiere_map[nume_f][key] = val
                                mutații_aplicate += 1
            except Exception:
                pass  # Ignorăm fișierele în curs de scriere

        print(f"   └─ ✅ Aplicat în memorie {mutații_aplicate} mutații ordonate cronologic.", flush=True)

    except Exception as e:
        print(f"⚠️ Eroare la citirea micro-indecșilor temporari: {e}", flush=True)

    return fisiere_map


def obtine_index_virtual(service):
    """
    1. Descarcă Master Index (index_xml.json).
    2. Scanează noutățile (Delta) apărute pe Drive după timestamp.
    3. CITEȘTE și aplică peste el toți micro-indecșii temporari ordonați cronologic.
    4. Returnează Indexul Virtual perfect, actualizat 100% la secundă!
    """
    data_master = descarca_index_master(service)
    fisiere_map = data_master.get("fisiere", {})
    last_updated = data_master.get("last_updated")

    pattern_nume = re.compile(r"brut_legislatie_(\d+)_pag(\d+)\.xml")
    noutati_gasite = 0

    # Step A: Căutăm Delta (fișiere XML noi create între timp)
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
        print(f"⚡ [Index Virtual] Identificate {noutati_gasite} fișiere XML ultra-noi apărute pe Drive.", flush=True)

    # Step B: Aplicăm în memorie toate micro-indecșii temporari netrecuți în Master (cronologic)
    fisiere_map = aplica_micro_indecsi_temporari_in_memorie(service, fisiere_map)

    data_master["fisiere"] = fisiere_map
    data_master["total_fisiere"] = len(fisiere_map)
    return data_master


def obtine_fisiere_neprocesate(service, nume_flag="Tags_extracted"):
    """
    Subrutină helper: Returnează o listă de fișiere neprocesate, 
    garantat curate (luând în calcul master-ul + noutățile + micro-indecșii neconsolidați).
    """
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
