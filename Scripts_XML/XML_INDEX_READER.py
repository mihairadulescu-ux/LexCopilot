import io
import json
import os
import re
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

CALE_INDEX_LOCAL = "index_xml.json"

DEFAULT_TEMP_FOLDER_ID = "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"

# ==========================================
# PRELUARE VARIABILE PUBLICE DIN MEDIU
# ==========================================
INDEX_FILE_ID = os.getenv("XML_STORAGE_INDEX", "").strip()

FOLDER_TEMP_INDEXES_ID = (
    os.getenv("TEMPORARY_XML_INDEXES", "").strip() or DEFAULT_TEMP_FOLDER_ID
)

FOLDER_METADATA_ID = (
    os.getenv("METADATA_FOLDER_ID", "").strip() or DEFAULT_TEMP_FOLDER_ID
)

FOLDERE_XML_RAW = os.getenv("DRIVE_FOLDER_XML", "").strip()
FOLDERE_XML_IDS = [
    fid.strip()
    for fid in FOLDERE_XML_RAW.replace("\n", "").replace("\r", "").split(",")
    if fid.strip()
] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2",
]


def descarca_index_master(service):
    """
    Descărcare directă a fișierului Main Index din Shared Drive.
    Include parametrii compleți de autorizare pentru Google Drive API v3.
    """
    target_id = INDEX_FILE_ID

    if not target_id:
        print(
            "ℹ️ [Index Reader] Variabila 'XML_STORAGE_INDEX' nu este setată. Se continuă pe micro-indecși.",
            flush=True,
        )
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}

    try:
        print(
            f"📥 [Index Reader] Descărcare Master Index din Shared Drive (ID: {target_id[:8]}...)...",
            flush=True,
        )

        # Pasul 1: Preluare stream media cu toate flag-urile de Shared Drive active
        cerere = service.files().get_media(
            fileId=target_id,
            supportsAllDrives=True
        )

        fh = io.FileIO(CALE_INDEX_LOCAL, "wb")
        downloader = MediaIoBaseDownload(
            fh, cerere, chunksize=10 * 1024 * 1024
        )

        gata = False
        while not gata:
            _, gata = downloader.next_chunk()

        with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(
                f"✅ [Index Reader] Master Index încărcat cu succes! ({len(data.get('fisiere', {}))} fișiere în baza master)",
                flush=True,
            )
            return data

    except HttpError as err:
        # Dacă prin get_media conexiunea directă e blocată pe Shared Drive, încercăm prin execute direct
        if err.resp.status == 404:
            try:
                print(
                    "🔄 [Index Reader] Reîncercare descărcare directă ca octeți (Shared Drive Bypass)...",
                    flush=True,
                )
                continut_bytes = (
                    service.files()
                    .get_media(fileId=target_id, supportsAllDrives=True)
                    .execute()
                )

                with open(CALE_INDEX_LOCAL, "wb") as f:
                    f.write(continut_bytes)

                with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(
                        f"✅ [Index Reader] Master Index descărcat cu succes via Direct Stream! ({len(data.get('fisiere', {}))} fișiere)",
                        flush=True,
                    )
                    return data
            except Exception as ex:
                print(
                    f"⚠️ [Index Reader] Descărcare Direct Stream eșuată: {ex}",
                    flush=True,
                )

        print(
            f"⚠️ [Index Reader] Master Index indisponibil pe Drive (ID: {target_id}): {err}",
            flush=True,
        )
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}
    except Exception as e:
        print(
            f"⚠️ [Index Reader] Eroare la descărcarea Master Index: {e}",
            flush=True,
        )
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}


def aplica_micro_indecsi_temporari_in_memorie(service, fisiere_map):
    """Citește din găleată și suprapune în memorie toate mutațiile din temp_index_*.json."""
    if not FOLDER_TEMP_INDEXES_ID:
        return fisiere_map

    query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
    try:
        resp = (
            service.files()
            .list(
                q=query,
                fields="files(id, name, createdTime)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        loguri_temp = resp.get("files", [])
        if not loguri_temp:
            return fisiere_map

        loguri_temp.sort(key=lambda x: x.get("createdTime", ""))
        print(
            f"⚡ [Index Reader] Aplicare {len(loguri_temp)} micro-indecși din TEMPORARY_XML_INDEXES...",
            flush=True,
        )

        mutații_aplicate = 0
        for log_file in loguri_temp:
            file_id = log_file["id"]
            try:
                content_bytes = (
                    service.files()
                    .get_media(fileId=file_id, supportsAllDrives=True)
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

        print(
            f"   └─ ✅ {mutații_aplicate} mutații aplicate în Indexul Virtual.",
            flush=True,
        )

    except Exception as e:
        print(
            f"⚠️ [Index Reader] Eroare la citirea micro-indecșilor: {e}",
            flush=True,
        )

    return fisiere_map


def obtine_index_virtual(service):
    """Construiește în memorie starea unificată la zi a tuturor fișierelor XML."""
    data_master = descarca_index_master(service)
    fisiere_map = data_master.get("fisiere", {})
    last_updated = data_master.get("last_updated")

    fisiere_map = aplica_micro_indecsi_temporari_in_memorie(
        service, fisiere_map
    )

    pattern_nume = re.compile(r"brut_legislatie_(\d+)_pag(\d+)\.xml")
    noutati_gasite = 0

    if last_updated:
        for folder_id in FOLDERE_XML_IDS:
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_' and modifiedTime > '{last_updated}' and trashed = false"
            page_token = None

            try:
                while True:
                    response = (
                        service.files()
                        .list(
                            q=query,
                            spaces="drive",
                            fields="nextPageToken, files(id, name, description)",
                            pageSize=1000,
                            pageToken=page_token,
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                        )
                        .execute()
                    )

                    files = response.get("files", [])
                    for f in files:
                        nume = f["name"]
                        if (
                            nume not in fisiere_map
                            or not fisiere_map[nume].get("id")
                        ):
                            desc = f.get("description", "")
                            match = pattern_nume.search(nume)
                            an_val = int(match.group(1)) if match else None
                            pag_val = int(match.group(2)) if match else None

                            fisiere_map[nume] = {
                                "id": f["id"],
                                "an": an_val,
                                "pagina": pag_val,
                                "downloaded": True,
                                "Tags_extracted": False,
                                "processed": ("processed=true" in desc),
                            }
                            noutati_gasite += 1

                    page_token = response.get("nextPageToken", None)
                    if not page_token:
                        break
            except Exception as e:
                print(
                    f"⚠️ [Index Reader] Eroare verificare delta în Shared Drive {folder_id[:8]}: {e}",
                    flush=True,
                )

    if noutati_gasite > 0:
        print(
            f"⚡ [Index Reader] Identificate {noutati_gasite} fișiere noi din scanarea Delta.",
            flush=True,
        )

    data_master["fisiere"] = fisiere_map
    data_master["total_fisiere"] = len(fisiere_map)
    return data_master


def obtine_fisiere_neprocesate(service, nume_flag="Tags_extracted"):
    """Filtrează Indexul Virtual pentru a returna fișierele neprocesate."""
    index_v = obtine_index_virtual(service)
    fisiere_map = index_v.get("fisiere", {})

    rezultat = []
    for nume, date in fisiere_map.items():
        if not date.get(nume_flag, False) and date.get("id"):
            item = dict(date)
            item["nume"] = nume
            rezultat.append(item)

    print(
        f"🎯 [Index Reader] Găsite {len(rezultat)} fișiere neprocesate pentru flagul '{nume_flag}'.",
        flush=True,
    )
    return rezultat
