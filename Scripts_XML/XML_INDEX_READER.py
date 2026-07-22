import os
import sys
import time
import json
import re
from pathlib import Path

# ==============================================================================
# CONFIGURARE CĂI DE IMPORT
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build

from drive_config import (
    FOLDERE_XML_IDS,
    FOLDER_TEMP_INDEXES_ID,
    get_file_params,
    get_list_params,
)

# MAPARE UNITARĂ PENTRU ID-UL MASTER INDEXULUI XML
INDEX_FILE_ID = (
    os.getenv("XML_STORAGE_INDEX")
    or os.getenv("INDEX_FILE_ID")
    or getattr(sys.modules.get("drive_config"), "XML_STORAGE_INDEX", None)
    or getattr(sys.modules.get("drive_config"), "INDEX_FILE_ID", None)
    or "1OkPgwX_F6FKwupuhD9kO3rynj4zdel0N"
)

# Regex flexibil pentru normalizare denumiri
PATTERN_XML_FLEXIBIL = re.compile(r"^brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)


# ==============================================================================
# INCARCARE MASTER INDEX DIN DRIVE
# ==============================================================================
def descarca_master_index(service):
    """Descarcă fișierul index_xml.json din Google Drive."""
    if not INDEX_FILE_ID:
        print("⚠️ [Index Reader] INDEX_FILE_ID nu este setat. Se pornește cu index gol.", flush=True)
        return {"fisiere": {}, "last_updated": ""}

    try:
        continut_bytes = (
            service.files()
            .get_media(**get_file_params(fileId=INDEX_FILE_ID, acknowledgeAbuse=True))
            .execute()
        )
        data = json.loads(continut_bytes.decode("utf-8"))
        print(f"✅ [Master Index Loaded] {len(data.get('fisiere', {})):,} fișiere existente în memorie.", flush=True)
        return data
    except Exception as e:
        print(f"⚠️ [Index Reader] Nu s-a putut descărca Master Index-ul ({e}). Se folosește index gol.", flush=True)
        return {"fisiere": {}, "last_updated": ""}


# ==============================================================================
# APLICARE MICRO-INDECȘI TEMPORARI (temp_index_*.json)
# ==============================================================================
def aplica_micro_indecsi(service, index_master):
    """
    Caută și aplică toate mutațiile din fișierele temporare temp_index_*.json
    create de alte procese paralele în FOLDER_TEMP_INDEXES_ID.
    """
    fisiere_map = index_master.get("fisiere", {})
    
    try:
        query_temp = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
        res = service.files().list(**get_list_params(q=query_temp, fields="files(id, name)")).execute()
        files = res.get("files", [])

        if not files:
            return index_master

        print(f"⚡ [Micro-Indecși] Aplicare {len(files)} fișiere temporare...", flush=True)
        total_mutatii = 0

        for f in files:
            try:
                content_bytes = (
                    service.files()
                    .get_media(**get_file_params(fileId=f["id"], acknowledgeAbuse=True))
                    .execute()
                )
                data_temp = json.loads(content_bytes.decode("utf-8"))
                flag_updates = data_temp.get("flag_updates", {})

                for nume_f, meta in flag_updates.items():
                    # Normalizăm denumirea la 'brut_XML_'
                    nume_normat = nume_f.replace("brut_legislatie_", "brut_XML_") if nume_f.startswith("brut_legislatie_") else nume_f
                    
                    if nume_normat not in fisiere_map:
                        # Dacă era stocat sub denumirea veche, facem transferul
                        nume_vechi = nume_f.replace("brut_XML_", "brut_legislatie_")
                        if nume_vechi in fisiere_map:
                            fisiere_map[nume_normat] = fisiere_map.pop(nume_vechi)
                        else:
                            fisiere_map[nume_normat] = {}

                    # Actualizăm metadatele/flag-urile
                    fisiere_map[nume_normat].update(meta)
                    total_mutatii += 1

            except Exception as e:
                print(f"⚠️ Eroare la citirea micro-index-ului {f['name']}: {e}", flush=True)

        print(f"   └─ ✅ Aplicat în memorie {total_mutatii:,} mutații din Micro-Indecși.", flush=True)
    except Exception as e:
        print(f"⚠️ Eroare la scanarea micro-indecșilor: {e}", flush=True)

    index_master["fisiere"] = fisiere_map
    return index_master


# ==============================================================================
# SCANARE DELTA (FIȘIERE NOI PE DRIVE)
# ==============================================================================
def scanare_delta_drive(service, index_master):
    """
    Scanează doar fișierele modificate/create pe Shared Drive-uri după data
    ultimei actualizări din Master Index (last_updated).
    """
    last_updated = index_master.get("last_updated", "")
    fisiere_map = index_master.get("fisiere", {})

    if not last_updated:
        return index_master

    # Formatăm data ISO pentru query-ul Google Drive
    data_iso = last_updated.replace(" ", "T") + "Z"
    print(f"🔍 SCANARE DELTA (fișiere modificate/create după {data_iso})...", flush=True)

    total_delta = 0
    for folder_id in FOLDERE_XML_IDS:
        query = f"'{folder_id}' in parents and modifiedTime > '{data_iso}' and trashed = false"
        page_token = None

        while True:
            try:
                res = service.files().list(
                    **get_list_params(
                        q=query,
                        fields="nextPageToken, files(id, name, createdTime, size)",
                        pageToken=page_token,
                        pageSize=1000
                    )
                ).execute()
                
                files = res.get("files", [])
                for f in files:
                    nume = f["name"]
                    # Compatibilitate flexibilă pentru ambele formate
                    match = PATTERN_XML_FLEXIBIL.match(nume)
                    if match:
                        nume_normat = f"brut_XML_{match.group(1)}_pag{match.group(2)}.xml"
                        
                        if nume_normat not in fisiere_map:
                            fisiere_map[nume_normat] = {
                                "id": f["id"],
                                "folder_id": folder_id,
                                "createdTime": f.get("createdTime", ""),
                                "size": int(f.get("size", 0)),
                                "downloaded": True,
                                "Tags_extracted": False,
                                "processed": False
                            }
                            total_delta += 1

                page_token = res.get("nextPageToken")
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Eroare la scanarea delta pe folderul {folder_id[:8]}: {e}", flush=True)
                break

    if total_delta > 0:
        print(f"   └─ ✅ Adăugate din Scanarea Delta: {total_delta:,} fișiere noi.", flush=True)

    index_master["fisiere"] = fisiere_map
    return index_master


# ==============================================================================
# API PUBLIC DE CITIRE INDEX VIRTUAL
# ==============================================================================
def obtine_index_virtual(service):
    """
    Funcția principală apelată de toate scripturile pentru a obține 
    starea LIVE completă și consolidată în memorie (3 secunde).
    """
    index_m = descarca_master_index(service)
    index_m = aplica_micro_indecsi(service, index_m)
    index_m = scanare_delta_drive(service, index_m)
    return index_m


def obtine_fisiere_neprocesate(service, nume_flag="Tags_extracted"):
    """
    Helper util pentru extragerea fișierelor care au flag-ul specified=False.
    """
    index_v = obtine_index_virtual(service)
    fisiere_map = index_v.get("fisiere", {})

    neprocesate = []
    for nume, meta in fisiere_map.items():
        if not meta.get(nume_flag, False):
            meta_copie = dict(meta)
            meta_copie["nume"] = nume
            neprocesate.append(meta_copie)

    return neprocesate
