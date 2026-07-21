import io
import json
import re
import sys
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from drive_config import (
    INDEX_FILE_ID,
    FOLDER_TEMP_INDEXES_ID,
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

CALE_INDEX_LOCAL = "index_xml.json"


def verifica_si_descarca_index_master(service):
    """PASUL 0 & 1: Verificare strictă și descărcare Master Index."""
    if not INDEX_FILE_ID:
        print("❌ [ABORT] Variabila 'XML_STORAGE_INDEX' este GOLĂ sau NESETATĂ!", flush=True)
        sys.exit(1)

    params_get = get_file_params(
        fileId=INDEX_FILE_ID,
        fields="id, name, size, mimeType, parents, trashed"
    )

    print("=" * 70, flush=True)
    print("🔍 [SHARED DRIVE DIAGNOSTIC] Verificare Master Index...", flush=True)
    print(f"   ├─ ID Fișier extras: '{INDEX_FILE_ID}'", flush=True)
    print(f"   └─ Parametri apel API: {params_get}", flush=True)

    # 1. VERIFICARE METADATE
    try:
        meta = service.files().get(**params_get).execute()
        size_mb = round(int(meta.get("size", 0)) / (1024 * 1024), 2)
        print(f"✅ [TEST REUSIT] Fișier identificat pe Shared Drive!", flush=True)
        print(f"   ├─ Nume: {meta.get('name')}", flush=True)
        print(f"   ├─ Dimensiune: {size_mb} MB", flush=True)
        print(f"   ├─ În Trash/Coș: {meta.get('trashed', False)}", flush=True)
        print(f"   └─ Folder Părinte ID: {meta.get('parents', [])}", flush=True)
        print("=" * 70, flush=True)
    except HttpError as err:
        print("\n" + "🚨 " * 10, flush=True)
        print("❌ [TEST EȘUAT - ABORT] Google Drive API a returnat o eroare!", flush=True)
        print(f"   ├─ Cod Status HTTP: {err.resp.status}", flush=True)
        print(f"   ├─ Motiv: {err._get_reason()}", flush=True)
        print(f"   └─ Detalii Eroare Nativă: {err.content.decode('utf-8')}", flush=True)
        print("🚨 " * 10 + "\n", flush=True)
        sys.exit(1)
    except Exception as ex:
        print(f"\n❌ [TEST EȘUAT - ABORT] Eroare neașteptată la interogare: {ex}", flush=True)
        sys.exit(1)

    # 2. DESCĂRCARE FIZICĂ MEDIA
    print(f"📥 Descărcare conținut Master Index ({CALE_INDEX_LOCAL})...", flush=True)
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
            print(f"✅ [Master Index] Descărcat și încărcat în memorie cu succes! ({total} fișiere)", flush=True)
            return data
    except Exception as e:
        print(f"❌ [ABORT] Eroare la descărcarea conținutului media: {e}", flush=True)
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

        print(f"   └─ ✅ Aplicat în memorie {mutații_aplicate} mutații.", flush=True)

    except Exception as e:
        print(f"⚠️ Eroare la citirea micro-indecșilor temporari: {e}", flush=True)

    return fisiere_map


def obtine_index_virtual(service):
    """Construiește starea unificată a bazei de date."""
    data_master = verifica_si_descarca_index_master(service)
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
                    response = (
                        service.files()
                        .list(**get_list_params(
                            q=query,
                            spaces="drive",
                            fields="nextPageToken, files(id, name, description)",
                            pageSize=1000,
                            pageToken=page_token,
                        ))
                        .execute()
                    )

                    files = response.get("files", [])
                    for f in files:
                        nume = f["name"]
                        if nume not in fisiere_map or not fisiere_map[nume].get("id"):
                            desc = f.get("description", "")
                            match = pattern_nume.search(nume)
                            an_val = int(match.group(1)) if match else None
                            pag_val = int(match.group(2)) if match else None

                            fisiere_map[nume] = {
                                "id": f["id"],
                                "folder_id": folder_id,
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
                print(f"⚠️ Eroare verificare delta folder {folder_id[:8]}: {e}", flush=True)

    if noutati_gasite > 0:
        print(f"⚡ [Delta Finală] Identificate {noutati_gasite} fișiere ultra-noi.", flush=True)

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
