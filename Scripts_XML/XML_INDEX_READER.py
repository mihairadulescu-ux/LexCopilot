import io
import json
import os
import re
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

CALE_INDEX_LOCAL = "index_xml.json"

DEFAULT_TEMP_FOLDER_ID = "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"

# 1. TEMPORARY_XML_INDEXES -> Găleata/Folderul unde stau micro-indecșii temp
FOLDER_TEMP_INDEXES_ID = (
    os.getenv("TEMPORARY_XML_INDEXES", "")
    .replace('"', "")
    .replace("'", "")
    .strip()
    or DEFAULT_TEMP_FOLDER_ID
)

# 2. XML_STORAGE_INDEX -> ID-ul direct al fișierului 'index_xml.json' (Main Index)
INDEX_FILE_ID = (
    os.getenv("XML_STORAGE_INDEX", "").replace('"', "").replace("'", "").strip()
)

FOLDERE_XML_RAW = (
    os.getenv("DRIVE_FOLDER_XML", "")
    .replace('"', "")
    .replace("'", "")
    .replace("\n", "")
    .replace("\r", "")
)
FOLDERE_XML_IDS = [
    fid.strip() for fid in FOLDERE_XML_RAW.split(",") if fid.strip()
] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2",
]


def descarca_index_master(service):
    """Descărcare directă sau căutare dinamică a fișierului Main Index."""
    target_id = INDEX_FILE_ID

    # Fallback: Dacă ID-ul direct nu e transmis în mediu, îl căutăm după nume în găleata de micro-indecși
    if not target_id and FOLDER_TEMP_INDEXES_ID:
        try:
            query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name = 'index_xml.json' and trashed = false"
            res = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="files(id, name)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )

            files = res.get("files", [])
            if files:
                target_id = files[0]["id"]
                print(
                    f"🔍 [Main Index] Detectat 'index_xml.json' în găleata temp (ID: {target_id[:8]}...)",
                    flush=True,
                )
        except Exception as e:
            print(f"⚠️ Căutare dinamică Main Index eșuată: {e}", flush=True)

    if not target_id:
        print(
            "ℹ️ 'XML_STORAGE_INDEX' nu este setat. Se începe cu un index vid local.",
            flush=True,
        )
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}

    try:
        # Descărcare Main Index direct cu supportsAllDrives=True
        cerere = service.files().get_media(
            fileId=target_id, supportsAllDrives=True
        )
        fh = io.FileIO(CALE_INDEX_LOCAL, "wb")
        downloader = MediaIoBaseDownload(fh, cerere)
        gata = False
        while not gata:
            _, gata = downloader.next_chunk()

        with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(
                f"📥 [Main Index] Descărcat cu succes! ({len(data.get('fisiere', {}))} fișiere în baza master)",
                flush=True,
            )
            return data
    except Exception as e:
        print(
            f"⚠️ Nu s-a putut descărca Main Index din Drive (ID: {target_id}): {e}",
            flush=True,
        )
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}


def aplica_micro_indecsi_temporari_in_memorie(service, fisiere_map):
    """Citește toate fișierele temp_index_*.json din găleata TEMPORARY_XML_INDEXES și aplică delta în memorie."""
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
            f"⚡ [Index Virtual] Citire {len(loguri_temp)} micro-indecși din găleată ({FOLDER_TEMP_INDEXES_ID[:8]}...)...",
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
            f"   └─ ✅ Aplicat în memorie {mutații_aplicate} mutații din micro-indecși.",
            flush=True,
        )

    except Exception as e:
        print(
            f"⚠️ Eroare la citirea micro-indecșilor temporari: {e}", flush=True
        )

    return fisiere_map


def obtine_index_virtual(service):
    # Step 1: Încarcă fișierul principal (Main Index)
    data_master = descarca_index_master(service)
    fisiere_map = data_master.get("fisiere", {})
    last_updated = data_master.get("last_updated")

    # Step 2: Aplică peste el toate micro-indecșii din găleată
    fisiere_map = aplica_micro_indecsi_temporari_in_memorie(
        service, fisiere_map
    )

    pattern_nume = re.compile(r"brut_legislatie_(\d+)_pag(\d+)\.xml")
    noutati_gasite = 0

    # Step 3: Verificare Delta rapidă pe fișierele noi apărute direct pe Drive după last_updated
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
                    f"⚠️ Eroare verificare delta folder {folder_id[:8]}: {e}",
                    flush=True,
                )

    if noutati_gasite > 0:
        print(
            f"⚡ [Verificare Delta] Identificate {noutati_gasite} fișiere XML ultra-noi pe Drive.",
            flush=True,
        )

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

    print(
        f"🎯 [Filtrare Target] Găsite {len(rezultat)} fișiere neprocesate pentru '{nume_flag}'.",
        flush=True,
    )
    return rezultat
