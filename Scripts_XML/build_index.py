import os
import sys
import time
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
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
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from drive_config import (
    INDEX_FILE_ID,
    FOLDER_TEMP_INDEXES_ID,
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

NUME_MASTER_INDEX_XML = "index_xml.json"


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API (ROBUSTĂ)
# ==============================================================================
def get_drive_service():
    """Creează un client Drive API robust cu timeout setat pentru prevenirea blocajelor."""
    socket.setdefaulttimeout(60)

    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )

    if creds_json:
        try:
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception as e:
            print(f"❌ Eroare la citirea secretului JSON: {e}", flush=True)
            sys.exit(1)

    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception as e:
            print(f"❌ Eroare la citirea fișierului local service_account.json: {e}", flush=True)

    print("❌ Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


# ==============================================================================
# PASUL 0: INCARCARE SNAPSHOT/BACKUP VECHIUL INDEX PENTRU PRESERVARE FLAG-URI
# ==============================================================================
def incarca_snapshot_index_vechi(service):
    """Descarcă indexul existent pentru a-i păstra flag-urile de stare (Tags_extracted, processed etc.)."""
    print("\n📦 [SNAPSHOT] Descărcare Index Vechi pentru conservarea stărilor...", flush=True)
    if not INDEX_FILE_ID:
        print("⚠️ INDEX_FILE_ID nu este definit. Se va porni fără istoric de flag-uri.", flush=True)
        return {}

    try:
        continut_bytes = (
            service.files()
            .get_media(**get_file_params(fileId=INDEX_FILE_ID, acknowledgeAbuse=True))
            .execute()
        )
        data = json.loads(continut_bytes.decode("utf-8"))
        fisiere_map = data.get("fisiere", {})
        print(f"✅ [SNAPSHOT REUȘIT] Am încărcat în memorie stările pentru {len(fisiere_map):,} fișiere existente!", flush=True)
        return fisiere_map
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca vechiul index ({e}). Se va construi fără istoric de flag-uri.", flush=True)
        return {}


# ==============================================================================
# SALVARE MASTER INDEX XML PE DRIVE
# ==============================================================================
def salveaza_master_index_xml(service, data, nume_fisier=NUME_MASTER_INDEX_XML, mesaj="Master Index XML"):
    data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cale_temp = Path(nume_fisier)
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        media = MediaFileUpload(str(cale_temp), mimetype="application/json")

        if INDEX_FILE_ID:
            params = get_file_params(fileId=INDEX_FILE_ID)
            params["media_body"] = media
            service.files().update(**params).execute()
        else:
            query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name = '{nume_fisier}' and trashed = false"
            list_params = get_list_params(q=query, fields="files(id)")
            res = service.files().list(**list_params).execute()
            files = res.get("files", [])

            if files:
                file_id = files[0]["id"]
                params = get_file_params(fileId=file_id)
                params["media_body"] = media
                service.files().update(**params).execute()
            else:
                file_metadata = {"name": nume_fisier, "parents": [FOLDER_TEMP_INDEXES_ID]}
                params = get_file_params()
                params["body"] = file_metadata
                params["media_body"] = media
                service.files().create(**params).execute()

        total_intrare = len(data.get("fisiere", data.get("inventory", {})))
        print(f"💾 {mesaj} salvat pe Drive! ({total_intrare:,} intrări)", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()
    except Exception as e:
        print(f"❌ Eroare la salvarea Master Index XML: {e}", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()


# ==============================================================================
# EXECUȚIE TRASH MULTI-THREADED
# ==============================================================================
def executa_trash_multi_threaded(ids_de_sters, max_workers=15):
    if not ids_de_sters:
        print("✨ Nu există duplicate de șters! Totul este curat.", flush=True)
        return

    print("\n" + "=" * 60, flush=True)
    print(f"🚀 TRIMITERE LA COȘ #{len(ids_de_sters):,} DUPLICATE XML ({max_workers} FIRE PARALELE)...", flush=True)
    print("=" * 60, flush=True)

    counter_lock = threading.Lock()
    total_curatate = 0
    erori_gunoi = 0
    timp_start = time.time()

    def trashing_worker(file_id):
        nonlocal total_curatate, erori_gunoi
        thread_service = get_drive_service()
        
        for incercare in range(10):
            try:
                params = get_file_params(fileId=file_id)
                params["body"] = {"trashed": True}
                thread_service.files().update(**params).execute()
                
                with counter_lock:
                    total_curatate += 1
                    if total_curatate % 200 == 0 or total_curatate == len(ids_de_sters):
                        durata = round(time.time() - timp_start, 1)
                        viteza = round(total_curatate / (durata if durata > 0 else 1), 1)
                        print(
                            f"⚡ [TURBO Trash XML] Mutate la coș #{total_curatate:,}/{len(ids_de_sters):,} | Ritm: {viteza} f/sec ({durata}s)",
                            flush=True,
                        )
                return True
            except Exception as e:
                pauza = min(2 ** incercare, 30)
                time.sleep(pauza)
                thread_service = get_drive_service()

        with counter_lock:
            erori_gunoi += 1
        return False

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(trashing_worker, ids_de_sters)

    durata_totala = round(time.time() - timp_start, 1)
    print("\n" + "=" * 60, flush=True)
    print(f"🏁 OPERAȚIUNE DE TRASH FINALIZATĂ în {durata_totala}s!", flush=True)
    print(f"🗑️ Duplicate XML mutate în coș: {total_curatate:,}", flush=True)
    if erori_gunoi > 0:
        print(f"⚠️ Erori întâmpinate la ștergere: {erori_gunoi:,}", flush=True)
    print("=" * 60 + "\n", flush=True)


# ==============================================================================
# MAIN ENGINE: RAW SCAN -> STATE MERGE -> CLEAN MASTER INDEX
# ==============================================================================
def main():
    print("============================================================", flush=True)
    print("🚀 FULL RAW INVENTORY & STATE PRESERVING CLEANUP - XML", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()
    
    # 1. Preluăm snapshot-ul cu vechile flag-uri de procesare
    old_index_map = incarca_snapshot_index_vechi(service)

    # Inventar global peste cele 4 Shared Drive-uri: { nume_fisier: [list_of_metadata] }
    raw_inventory = {}
    total_fisiere_gasite = 0
    fisiere_de_la_ultimul_save = 0

    # 2. Scanare fizică Cross-Drive
    for index_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n📂 [{index_folder}/{len(FOLDERE_XML_IDS)}] Scanare Drive XML Folder ID: {folder_id}...", flush=True)
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            response = None
            incercare = 0

            # BUCLĂ PERSISTENTĂ PE PAGE TOKEN
            while True:
                try:
                    list_params = get_list_params(
                        q=query,
                        fields="nextPageToken, files(id, name, createdTime, size)",
                        pageToken=page_token,
                        pageSize=1000,
                    )
                    response = service.files().list(**list_params).execute()
                    break
                except (socket.error, socket.timeout, HttpError, Exception) as e:
                    incercare += 1
                    pauza = min(2 ** incercare, 30)
                    print(f"⚠️ Connection Error pe pageToken ({incercare}): {e}. Pauză {pauza}s și reîncercăm...", flush=True)
                    time.sleep(pauza)
                    service = get_drive_service()

            files = response.get("files", [])
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
                raw_inventory[nume].append(meta_item)

            if fisiere_de_la_ultimul_save >= 10000:
                fisiere_de_la_ultimul_save = 0
                print(f"📊 [Progres Scanare RAW] {total_fisiere_gasite:,} fișiere fizice parcurse...", flush=True)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    print(f"\n📊 SCANARE CROSS-DRIVE FINALIZATĂ!")
    print(f"📊 TOTAL FIȘIERE FIZICE PARCURSE PE CELE 4 DRIVE-URI: {total_fisiere_gasite:,}", flush=True)
    print(f"📊 GRUPURI DE NUME UNICE IDENTIFICATE: {len(raw_inventory):,}", flush=True)

    # ==========================================================================
    # 3. CONSOLIDARE ÎN MEMORIE ȘI TRANSFER DE STARE (MERGE)
    # ==========================================================================
    print("\n" + "=" * 60, flush=True)
    print("🧠 ANALIZĂ, SORTARE ȘI PRESERVARE FLAG-URI DE PROCESARE...", flush=True)
    print("=" * 60, flush=True)

    master_index = {"fisiere": {}, "total_fisiere": 0, "last_updated": ""}
    ids_de_sters = []
    stari_recuperate = 0

    for nume_fisier, lista_variante in raw_inventory.items():
        if len(lista_variante) == 1:
            castigator = lista_variante[0]
        else:
            # Sortăm: preferă fișierele cu size > 0 și cel mai recent createdTime
            lista_variante.sort(
                key=lambda x: (x["size"] > 0, x["createdTime"]), 
                reverse=True
            )
            castigator = lista_variante[0]
            
            for duplicat in lista_variante[1:]:
                ids_de_sters.append(duplicat["id"])

        # Preluăm starea veche (flag-urile de prelucrare) dacă fișierul a mai fost procesat anterior
        vechea_stare = old_index_map.get(nume_fisier, {})
        if vechea_stare:
            stari_recuperate += 1

        # Construim intrarea curată în noul Master Index
        master_index["fisiere"][nume_fisier] = {
            "id": castigator["id"],
            "folder_id": castigator["folder_id"],
            "createdTime": castigator["createdTime"],
            "size": castigator["size"],
            "downloaded": vechea_stare.get("downloaded", True),
            "Tags_extracted": vechea_stare.get("Tags_extracted", False),
            "processed": vechea_stare.get("processed", False)
        }

        # Transferăm orice alt flag personalizat existent în vechiul index
        for cheie, valoare in vechea_stare.items():
            if cheie not in master_index["fisiere"][nume_fisier]:
                master_index["fisiere"][nume_fisier][cheie] = valoare

    master_index["total_fisiere"] = len(master_index["fisiere"])

    print(f"✅ Fișiere XML validate drept MASTER: {master_index['total_fisiere']:,}", flush=True)
    print(f"🛡️ Stări/Flag-uri de procesare conservate din indexul vechi: {stari_recuperate:,}", flush=True)
    print(f"🗑️ Duplicate XML identificate pentru eliminare: {len(ids_de_sters):,}", flush=True)

    # 4. Executăm curățarea duplicatelor
    if ids_de_sters:
        executa_trash_multi_threaded(ids_de_sters, max_workers=15)

    # 5. Salvăm varianta finală curată cu toate flag-urile conservate
    salveaza_master_index_xml(
        service, 
        master_index, 
        nume_fisier=NUME_MASTER_INDEX_XML, 
        mesaj="Master Index XML Final Curat (Cu Stări Conservate)"
    )


if __name__ == "__main__":
    main()
