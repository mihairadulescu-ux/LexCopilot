import sys
import os
import time
import json
import socket
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Printăm direct pe STDOUT cu flush instant
sys.stdout.write("============================================================\n")
sys.stdout.write("🚀 SCRIPTUL BUILD_INDEX.PY A PORNIT FIZIC ÎN RUNNER!\n")
sys.stdout.write("============================================================\n")
sys.stdout.flush()

# Setăm timeout dur pe socket global (30s max pe orice cerere de rețea)
socket.setdefaulttimeout(30)

# Configurare căi de import
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from drive_config import (
    FOLDER_TEMP_INDEXES_ID,
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

INDEX_FILE_ID = (
    os.getenv("XML_STORAGE_INDEX")
    or os.getenv("INDEX_FILE_ID")
    or getattr(sys.modules.get("drive_config"), "XML_STORAGE_INDEX", None)
    or getattr(sys.modules.get("drive_config"), "INDEX_FILE_ID", None)
    or "1OkPgwX_F6FKwupuhD9kO3rynj4zdel0N"
)

NUME_MASTER_INDEX_XML = "index_xml.json"


def get_drive_service():
    sys.stdout.write("🔑 Conectare Google Drive API...\n")
    sys.stdout.flush()

    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )

    if not creds_json:
        sys.stdout.write("❌ NU S-A GĂSIT SECRETUL GOOGLE_SERVICE_ACCOUNT_JSON!\n")
        sys.stdout.flush()
        sys.exit(1)

    try:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        sys.stdout.write("✅ Conexiune Drive API stabilită cu succes!\n")
        sys.stdout.flush()
        return service
    except Exception as e:
        sys.stdout.write(f"❌ Eroare la autentificare: {e}\n")
        sys.stdout.flush()
        sys.exit(1)


def salveaza_master_index_xml(service, data, nume_fisier=NUME_MASTER_INDEX_XML, mesaj="Master Index XML"):
    data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cale_temp = Path(nume_fisier)
    
    for incercare in range(5):
        try:
            current_service = get_drive_service() if incercare > 0 else service

            with open(cale_temp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            media = MediaFileUpload(str(cale_temp), mimetype="application/json")

            if INDEX_FILE_ID:
                params = get_file_params(fileId=INDEX_FILE_ID)
                params["media_body"] = media
                current_service.files().update(**params).execute()
            else:
                query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name = '{nume_fisier}' and trashed = false"
                list_params = get_list_params(q=query, fields="files(id)")
                res = current_service.files().list(**list_params).execute()
                files = res.get("files", [])

                if files:
                    file_id = files[0]["id"]
                    params = get_file_params(fileId=file_id)
                    params["media_body"] = media
                    current_service.files().update(**params).execute()
                else:
                    file_metadata = {"name": nume_fisier, "parents": [FOLDER_TEMP_INDEXES_ID]}
                    params = get_file_params()
                    params["body"] = file_metadata
                    params["media_body"] = media
                    current_service.files().create(**params).execute()

            total_intrare = len(data.get("fisiere", data.get("inventory", {})))
            sys.stdout.write(f"💾 {mesaj} salvat pe Drive cu succes! ({total_intrare:,} intrări)\n")
            sys.stdout.flush()
            if cale_temp.exists():
                cale_temp.unlink()
            return True
        except Exception as e:
            sys.stdout.write(f"⚠️ Eroare la salvarea indexului pe Drive (încercarea {incercare + 1}/5): {e}\n")
            sys.stdout.flush()
            time.sleep(3)

    if cale_temp.exists():
        cale_temp.unlink()
    sys.stdout.write("❌ CRITICAL: Nu s-a putut salva indexul pe Drive după 5 încercări!\n")
    sys.stdout.flush()
    return False


def curata_micro_indecsi_procesati(service):
    try:
        query_temp = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
        res = service.files().list(**get_list_params(q=query_temp, fields="files(id, name)")).execute()
        files = res.get("files", [])

        if files:
            sys.stdout.write(f"\n🧹 Curățare {len(files)} fișiere de micro-index temporare...\n")
            sys.stdout.flush()
            for f in files:
                try:
                    params = get_file_params(fileId=f["id"])
                    params["body"] = {"trashed": True}
                    service.files().update(**params).execute()
                except Exception as e:
                    sys.stdout.write(f"⚠️ Nu s-a putut șterge micro-indexul {f['name']}: {e}\n")
                    sys.stdout.flush()
            sys.stdout.write("✅ Micro-indecșii temporari au fost curățați cu succes!\n")
            sys.stdout.flush()
    except Exception as e:
        sys.stdout.write(f"⚠️ Eroare la curățarea micro-indecșilor: {e}\n")
        sys.stdout.flush()


def executa_trash_multi_threaded(ids_de_sters, max_workers=15):
    if not ids_de_sters:
        sys.stdout.write("✨ Nu există fișiere goale sau duplicate de șters!\n")
        sys.stdout.flush()
        return

    sys.stdout.write(f"\n🚀 TRIMITERE LA COȘ #{len(ids_de_sters):,} FIȘIERE CU {max_workers} FIRE PARALELE...\n")
    sys.stdout.flush()

    counter_lock = threading.Lock()
    total_curatate = 0
    erori_gunoi = 0
    timp_start = time.time()

    def trashing_worker(file_id):
        nonlocal total_curatate, erori_gunoi
        thread_service = get_drive_service()
        
        for incercare in range(5):
            try:
                params = get_file_params(fileId=file_id)
                params["body"] = {"trashed": True}
                thread_service.files().update(**params).execute()
                
                with counter_lock:
                    total_curatate += 1
                    if total_curatate % 200 == 0 or total_curatate == len(ids_de_sters):
                        durata = round(time.time() - timp_start, 1)
                        sys.stdout.write(f"⚡ [TURBO Trash] Mutate la coș #{total_curatate:,}/{len(ids_de_sters):,} ({durata}s)\n")
                        sys.stdout.flush()
                return True
            except Exception:
                time.sleep(2)
                thread_service = get_drive_service()

        with counter_lock:
            erori_gunoi += 1
        return False

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(trashing_worker, ids_de_sters)


def main():
    sys.stdout.write("🚀 Intrăm în main()...\n")
    sys.stdout.flush()
    
    service = get_drive_service()

    raw_inventory = {}
    total_fisiere_gasite = 0
    fisiere_de_la_ultimul_save = 0
    timp_start = time.time()

    for index_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        sys.stdout.write(f"\n🔍 [{index_folder}/{len(FOLDERE_XML_IDS)}] Scanăm folderul Drive ID: {folder_id}...\n")
        sys.stdout.flush()
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        seen_tokens = set()

        while True:
            if page_token in seen_tokens:
                break
            if page_token:
                seen_tokens.add(page_token)

            try:
                list_params = get_list_params(
                    q=query,
                    fields="nextPageToken, files(id, name, createdTime, size)",
                    pageToken=page_token,
                    pageSize=1000,
                )
                response = service.files().list(**list_params).execute()
            except Exception as e:
                sys.stdout.write(f"⚠️ Eroare/Timeout la citire pagină Drive ({e}). Reîncercăm în 2s...\n")
                sys.stdout.flush()
                time.sleep(2)
                service = get_drive_service()
                continue

            files = response.get("files", [])
            
            if not files:
                break

            for f in files:
                nume = f["name"]
                total_fisiere_gasite += 1
                fisiere_de_la_ultimul_save += 1
                
                meta_item = {
                    "id": f["id"],
                    "folder_id": folder_id,
                    "createdTime": f.get("createdTime", "1970-01-01T00:00:00.000Z"),
                    "size": int(f.get("size", 0))
                }

                if nume not in raw_inventory:
                    raw_inventory[nume] = []

                if not any(x["id"] == f["id"] for x in raw_inventory[nume]):
                    raw_inventory[nume].append(meta_item)

            durata_partiala = round(time.time() - timp_start, 1)
            sys.stdout.write(f"   ⏳ [LIVE] Scanate: {total_fisiere_gasite:,} fișiere fizice ({durata_partiala}s)...\n")
            sys.stdout.flush()

            if fisiere_de_la_ultimul_save >= 10000:
                fisiere_de_la_ultimul_save = 0
                salveaza_master_index_xml(
                    service, 
                    {"inventory": raw_inventory}, 
                    nume_fisier=NUME_MASTER_INDEX_XML, 
                    mesaj=f"Backup Interimar RAW Inventar ({total_fisiere_gasite:,} fișiere)"
                )

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    sys.stdout.write(f"\n📊 TOTAL FIȘIERE FIZICE PARCURSE: {total_fisiere_gasite:,}\n")
    sys.stdout.flush()

    pattern_xml = re.compile(r"^brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)
    grupuri_semantice = {}
    ids_de_sters = []

    for nume_fisier, lista_variante in raw_inventory.items():
        match = pattern_xml.match(nume_fisier)
        cheie_semantica = f"{match.group(1)}_pag{match.group(2)}" if match else nume_fisier

        if cheie_semantica not in grupuri_semantice:
            grupuri_semantice[cheie_semantica] = []

        for v in lista_variante:
            v_copie = dict(v)
            v_copie["_nume_fisier"] = nume_fisier
            grupuri_semantice[cheie_semantica].append(v_copie)

    master_index = {"fisiere": {}, "total_fisiere": 0, "last_updated": ""}

    for cheie_semantica, lista_variante in grupuri_semantice.items():
        variante_valide = [v for v in lista_variante if v["size"] >= 10]
        variante_mici = [v for v in lista_variante if v["size"] < 10]

        for v_mica in variante_mici:
            ids_de_sters.append(v_mica["id"])

        if not variante_valide:
            continue

        variante_valide.sort(
            key=lambda x: (1 if x["_nume_fisier"].startswith("brut_XML_") else 0, x["createdTime"]),
            reverse=True
        )
        castigator = variante_valide[0]
        
        for duplicat in variante_valide[1:]:
            ids_de_sters.append(duplicat["id"])

        nume_master = castigator["_nume_fisier"].replace("brut_legislatie_", "brut_XML_")

        master_index["fisiere"][nume_master] = {
            "id": castigator["id"],
            "folder_id": castigator["folder_id"],
            "createdTime": castigator["createdTime"],
            "size": castigator["size"],
            "downloaded": True,
            "Tags_extracted": False,
            "processed": False
        }

    master_index["total_fisiere"] = len(master_index["fisiere"])

    salveaza_master_index_xml(service, master_index, nume_fisier=NUME_MASTER_INDEX_XML, mesaj="Master Index XML Final")

    if ids_de_sters:
        executa_trash_multi_threaded(ids_de_sters, max_workers=15)

    curata_micro_indecsi_procesati(service)
    sys.stdout.write("\n🎉 REINDEXARE COMPLETĂ FINALIZATĂ!\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        sys.stdout.write(f"\n❌ EROARE FATALĂ ÎN SCRIPT: {err}\n")
        sys.stdout.flush()
        sys.exit(1)
