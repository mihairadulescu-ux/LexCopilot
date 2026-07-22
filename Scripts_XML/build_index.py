import io
import json
import re
import sys
import time
import socket
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

# Rezolvare automată căi de import
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))

from drive_config import (
    INDEX_FILE_ID,
    FOLDER_TEMP_INDEXES_ID,
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

CALE_INDEX_LOCAL = "index_xml.json"


def get_drive_service_internal():
    """Client intern scurt cu socket timeout pentru operațiunile de curățare pe Delta."""
    socket.setdefaulttimeout(60)
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )
    if creds_json:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    
    cale_local = Path(__file__).resolve().parent.parent / "service_account.json"
    if cale_local.exists():
        creds = service_account.Credentials.from_service_account_file(
            str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    return None


def curata_duplicate_delta_multi_threaded(ids_de_sters, max_workers=10):
    """Șterge rapid la coș duplicatele identificate în timpul scanării Delta."""
    if not ids_de_sters:
        return

    print(f"🧹 [Auto-Trash Delta] S-au găsit {len(ids_de_sters)} duplicate noi pe Drive. Se trimit la coș...", flush=True)
    
    def trash_worker(file_id):
        srv = get_drive_service_internal()
        if not srv:
            return
        for _ in range(5):
            try:
                params = get_file_params(fileId=file_id)
                params["body"] = {"trashed": True}
                srv.files().update(**params).execute()
                return
            except Exception:
                time.sleep(1)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(trash_worker, ids_de_sters)
    print(f"✨ [Auto-Trash Delta] {len(ids_de_sters)} duplicate eliminate cu succes!", flush=True)


def verifica_si_descarca_index_master(service):
    """PASUL 0 & 1: Verificare strictă și descărcare Master Index."""
    if not INDEX_FILE_ID:
        print("❌ [ABORT] Variabila 'XML_STORAGE_INDEX' este GOLĂ sau NESETATĂ!", flush=True)
        sys.exit(1)

    params_get = get_file_params(
        fileId=INDEX_FILE_ID,
        fields="id, name, size, mimeType, parents, trashed"
    )

    try:
        meta = service.files().get(**params_get).execute()
        size_mb = round(int(meta.get("size", 0)) / (1024 * 1024), 2)
        print(f"✅ [Master Index Identificat] Nume: {meta.get('name')} | MB: {size_mb}", flush=True)
    except Exception as ex:
        print(f"❌ [ABORT] Eroare la citire metadate Master Index: {ex}", flush=True)
        sys.exit(1)

    try:
        continut_bytes = (
            service.files()
            .get_media(**get_file_params(fileId=INDEX_FILE_ID, acknowledgeAbuse=True))
            .execute()
        )

        with open(CALE_INDEX_LOCAL, "wb") as f:
            f.write(continut_bytes)

        with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
            data = json.load(f)
            total = len(data.get("fisiere", {}))
            print(f"✅ [Master Index Loaded] {total:,} fișiere existente în memorie.", flush=True)
            return data
    except Exception as e:
        print(f"❌ [ABORT] Eroare descărcare Master Index: {e}", flush=True)
        sys.exit(1)


def aplica_micro_indecsi_temporari_in_memorie(service, fisiere_map):
    """Citește și aplică micro-indecșii temporari din TEMPORARY_XML_INDEXES."""
    if not FOLDER_TEMP_INDEXES_ID:
        return fisiere_map

    query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
    try:
        resp = (
            service.files()
            .list(**get_list_params(q=query, fields="files(id, name, createdTime)"))
            .execute()
        )

        loguri_temp = resp.get("files", [])
        if not loguri_temp:
            return fisiere_map

        loguri_temp.sort(key=lambda x: x.get("createdTime", ""))
        print(f"⚡ [Micro-Indecși] Aplicare {len(loguri_temp)} fișiere temporare...", flush=True)

        mutații_aplicate = 0
        for log_file in loguri_temp:
            file_id = log_file["id"]
            try:
                content_bytes = (
                    service.files()
                    .get_media(**get_file_params(fileId=file_id, acknowledgeAbuse=True))
                    .execute()
                )
                data_log = json.loads(content_bytes.decode("utf-8"))
                flag_updates = data_log.get("flag_updates", {})

                for nume_f, modi_flags in flag_updates.items():
                    if isinstance(modi_flags, dict):
                        if modi_flags.get("_deleted") is True:
                            if nume_f in fisiere_map:
                                del fisiere_map[nume_f]
                                mutații_aplicate += 1
                        else:
                            if nume_f not in fisiere_map:
                                fisiere_map[nume_f] = {}
                            fisiere_map[nume_f].update(modi_flags)
                            mutații_aplicate += 1
            except HttpError as err:
                if err.resp.status in [404, 410]:
                    continue
            except Exception:
                pass

        print(f"   └─ ✅ Aplicat în memorie {mutații_aplicate} mutații din Micro-Indecși.", flush=True)

    except Exception as e:
        print(f"⚠️ Eroare la citirea micro-indecșilor temporari: {e}", flush=True)

    return fisiere_map


def obtine_index_virtual(service):
    """
    Construiește starea unificată a bazei de date.
    Dacă găsește fișiere duplicate nou create pe Drive (Delta), le elimină AUTOMAT la coș!
    """
    data_master = verifica_si_descarca_index_master(service)
    fisiere_map = data_master.get("fisiere", {})
    last_updated = data_master.get("last_updated")

    fisiere_map = aplica_micro_indecsi_temporari_in_memorie(service, fisiere_map)

    pattern_nume = re.compile(r"brut_legislatie_(\d+)_pag(\d+)\.xml")
    
    # Mapare pentru colectarea delta-ului și identificarea duplicatelor:
    # { nume_fisier: [list_of_drive_candidates] }
    delta_candidates = {}
    ids_de_sters_delta = []

    if last_updated:
        print(f"🔍 SCANARE DELTA (fișiere modificate/create după {last_updated})...", flush=True)
        for folder_id in FOLDERE_XML_IDS:
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_' and modifiedTime > '{last_updated}' and trashed = false"
            page_token = None

            try:
                while True:
                    response = (
                        service.files()
                        .list(**get_list_params(
                            q=query,
                            spaces="drive",
                            fields="nextPageToken, files(id, name, description, createdTime, size)",
                            pageSize=1000,
                            pageToken=page_token,
                        ))
                        .execute()
                    )

                    files = response.get("files", [])
                    for f in files:
                        nume = f["name"]
                        item_meta = {
                            "id": f["id"],
                            "folder_id": folder_id,
                            "createdTime": f.get("createdTime", "1970-01-01T00:00:00.000Z"),
                            "size": int(f.get("size", 0)),
                            "description": f.get("description", "")
                        }

                        if nume not in delta_candidates:
                            delta_candidates[nume] = []
                        delta_candidates[nume].append(item_meta)

                    page_token = response.get("nextPageToken", None)
                    if not page_token:
                        break
            except Exception as e:
                print(f"⚠️ Eroare verificare delta folder {folder_id[:8]}: {e}", flush=True)

    # --------------------------------------------------------------------------
    # PROCESARE DELTA & DEDUPLICARE AUTOMATĂ LA COȘ (AUTO-TRASH DELTA)
    # --------------------------------------------------------------------------
    noutati_validate = 0
    if delta_candidates:
        for nume_f, variante in delta_candidates.items():
            # Alege cel mai bun candidat
            variante.sort(key=lambda x: (x["size"] > 0, x["createdTime"]), reverse=True)
            castigator = variante[0]

            # Dacă existau duplicate în noua sesiune Delta, restul merg la coș!
            for dup in variante[1:]:
                ids_de_sters_delta.append(dup["id"])

            # Dacă în Master Index exista deja un fișier cu același nume, dar cu alt ID:
            if nume_f in fisiere_map and fisiere_map[nume_f].get("id"):
                vechiul_id = fisiere_map[nume_f]["id"]
                if vechiul_id != castigator["id"]:
                    # Vechiul ID devine duplicat și trimis la coș!
                    ids_de_sters_delta.append(vechiul_id)

            match = pattern_nume.search(nume_f)
            an_val = int(match.group(1)) if match else None
            pag_val = int(match.group(2)) if match else None

            # Actualizăm sau adăugăm în Indexul Virtual
            str_desc = castigator["description"]
            stare_existenta = fisiere_map.get(nume_f, {})

            fisiere_map[nume_f] = {
                "id": castigator["id"],
                "folder_id": castigator["folder_id"],
                "an": an_val,
                "pagina": pag_val,
                "createdTime": castigator["createdTime"],
                "size": castigator["size"],
                "downloaded": True,
                "Tags_extracted": stare_existenta.get("Tags_extracted", False),
                "processed": stare_existenta.get("processed", ("processed=true" in str_desc)),
            }
            noutati_validate += 1

        print(f"⚡ [Delta Processed] Integrate {noutati_validate} fișiere noi în Indexul Virtual.", flush=True)

    # Executăm curățarea duplicatelor Delta (dacă s-au găsit)
    if ids_de_sters_delta:
        curata_duplicate_delta_multi_threaded(ids_de_sters_delta)

    data_master["fisiere"] = fisiere_map
    data_master["total_fisiere"] = len(fisiere_map)
    return data_master


def obtine_fisiere_neprocesate(service, nume_flag="Tags_extracted"):
    index_v = obtine_index_virtual(service)
    fisiere_map = index_v.get("fisiere", {})

    rezultat = []
    for nume, date in fisiere_map.items():
        if not date.get(nume_flag, False) and date.get("id"):
            item = dict(date)
            item["nume"] = nume
            rezultat.append(item)

    print(f"🎯 [Filtrare Target] Găsite {len(rezultat)} fișiere neprocesate pentru '{nume_flag}'.", flush=True)
    return rezultat
