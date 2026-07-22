import os
import sys
import json
import time
from pathlib import Path

# ==============================================================================
# CONFIGURARE CĂI DE IMPORT
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))

from drive_config import (
    INDEX_FILE_ID,
    FOLDER_TEMP_INDEXES_ID,
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)


def formateaza_timestamp_iso(last_updated_str):
    """
    Formatează un string de dată în formatul ISO 8601 cerut strict de Google Drive API.
    Exemplu transformare: "2026-07-22 06:21:56" -> "2026-07-22T06:21:56Z"
    """
    if not last_updated_str:
        return "1970-01-01T00:00:00Z"
    
    ts = str(last_updated_str).strip().replace(" ", "T")
    
    if not ts.endswith("Z") and "+" not in ts:
        ts += "Z"
        
    return ts


def obtine_index_virtual(service):
    """
    Construiește în memorie starea unificată a fișierelor XML:
    1. Descarcă Master Index (index_xml.json).
    2. Aplică modificările din Micro-Indecși (temp_index_*.json).
    3. Scanează Delta pe cele 4 Shared Drive-uri pentru fișiere create după `last_updated`.
    """
    index_virtual = {"fisiere": {}, "last_updated": ""}

    # --------------------------------------------------------------------------
    # 1. ÎNCĂRCARE MASTER INDEX (index_xml.json)
    # --------------------------------------------------------------------------
    if INDEX_FILE_ID:
        try:
            params = get_file_params(fileId=INDEX_FILE_ID, acknowledgeAbuse=True)
            res = service.files().get_media(**params).execute()
            data = json.loads(res.decode("utf-8"))
            index_virtual["fisiere"] = data.get("fisiere", {})
            index_virtual["last_updated"] = data.get("last_updated", "")
            
            size_mb = round(len(res) / (1024 * 1024), 2)
            print(f"✅ [Master Index Identificat] Nume: index_xml.json | MB: {size_mb}", flush=True)
            print(f"✅ [Master Index Loaded] {len(index_virtual['fisiere']):,} fișiere existente în memorie.", flush=True)
        except Exception as e:
            print(f"⚠️ Nu s-a putut încărca Master Index ({e}). Se pornește de la zero.", flush=True)

    # --------------------------------------------------------------------------
    # 2. APLICARE MICRO-INDECȘI (temp_index_*.json)
    # --------------------------------------------------------------------------
    try:
        query_temp = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
        res_temp = service.files().list(**get_list_params(q=query_temp, fields="files(id, name)")).execute()
        fisiere_temp = res_temp.get("files", [])

        if fisiere_temp:
            print(f"⚡ [Micro-Indecși] Aplicare {len(fisiere_temp)} fișiere temporare...", flush=True)
            mutatii_totale = 0

            for f_temp in fisiere_temp:
                try:
                    params_t = get_file_params(fileId=f_temp["id"], acknowledgeAbuse=True)
                    content_bytes = service.files().get_media(**params_t).execute()
                    t_data = json.loads(content_bytes.decode("utf-8"))
                    flag_updates = t_data.get("flag_updates", {})

                    for nume_f, mutatie in flag_updates.items():
                        if nume_f not in index_virtual["fisiere"]:
                            index_virtual["fisiere"][nume_f] = {}
                        index_virtual["fisiere"][nume_f].update(mutatie)
                        mutatii_totale += 1

                except Exception as e_t:
                    print(f"⚠️ Eroare la citirea micro-indexului {f_temp['name']}: {e_t}", flush=True)

            print(f"   └─ ✅ Aplicat în memorie {mutatii_totale:,} mutații din Micro-Indecși.", flush=True)
    except Exception as e:
        print(f"⚠️ Eroare la scanarea micro-indecșilor: {e}", flush=True)

    # --------------------------------------------------------------------------
    # 3. SCANARE DELTA PE SHARED DRIVE-URI (CU FORMAT ISO NORM)
    # --------------------------------------------------------------------------
    last_updated = index_virtual.get("last_updated", "")
    if last_updated:
        timestamp_iso = formateaza_timestamp_iso(last_updated)
        print(f"🔍 SCANARE DELTA (fișiere modificate/create după {timestamp_iso})...", flush=True)

        for folder_id in FOLDERE_XML_IDS:
            try:
                # Query corectat cu T și Z conform standardului Google Drive API ISO 8601
                query_delta = (
                    f"'{folder_id}' in parents and name contains 'brut_legislatie_' "
                    f"and modifiedTime > '{timestamp_iso}' and trashed = false"
                )
                
                list_params = get_list_params(
                    q=query_delta,
                    fields="nextPageToken, files(id, name, createdTime, size)",
                    pageSize=1000
                )
                
                res_delta = service.files().list(**list_params).execute()
                files_delta = res_delta.get("files", [])

                for f_d in files_delta:
                    nume = f_d["name"]
                    size = int(f_d.get("size", 0))

                    # Ignorăm fișierele corupte / goale sub 10 baiți
                    if size < 10:
                        continue

                    if nume not in index_virtual["fisiere"]:
                        index_virtual["fisiere"][nume] = {
                            "id": f_d["id"],
                            "folder_id": folder_id,
                            "createdTime": f_d.get("createdTime", ""),
                            "size": size,
                            "downloaded": True,
                            "processed": False
                        }
            except Exception as e_d:
                print(f"⚠️ Eroare verificare delta folder {folder_id[:8]}: {e_d}", flush=True)

    return index_virtual


def obtine_fisiere_neprocesate(service, nume_flag="processed"):
    """
    Returnează o listă de dicționare cu fișierele din Index Virtual care
    au flag-ul specificat setat pe False.
    """
    index_v = obtine_index_virtual(service)
    fisiere_map = index_v.get("fisiere", {})
    neprocesate = []

    for nume, meta in fisiere_map.items():
        if not meta.get(nume_flag, False):
            item = dict(meta)
            item["nume"] = nume
            neprocesate.append(item)

    return neprocesate
