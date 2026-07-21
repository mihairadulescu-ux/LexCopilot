import os
import sys
import time
import json
import threading
import socket
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
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError
import io

from drive_config import (
    FOLDERE_XML_IDS,
    FOLDER_TEMP_INDEXES_ID,
    get_file_params,
    get_list_params,
)

NUME_MASTER_INDEX = "master_index.json"


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API (CU RECONECTARE LA BROKEN PIPE)
# ==============================================================================
def get_drive_service():
    """Creează un client Drive API robust cu timeout setat pentru prevenirea Broken Pipe."""
    # Setăm un default socket timeout global pentru a preveni blocajele nedefinite
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
# OPERAȚIUNI CU MASTER INDEX
# ==============================================================================
def descarca_master_index(service):
    print(f"📥 Descărcare {NUME_MASTER_INDEX} din Drive...", flush=True)
    query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name = '{NUME_MASTER_INDEX}' and trashed = false"
    try:
        list_params = get_list_params(q=query, fields="files(id)")
        res = service.files().list(**list_params).execute()
        files = res.get("files", [])
        if files:
            file_id = files[0]["id"]
            file_params = get_file_params(fileId=file_id)
            request = service.files().get_media(**file_params)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            data = json.loads(fh.read().decode("utf-8"))
            print(f"✅ Master Index încărcat! ({len(data.get('fisiere', {})):,} fișiere unice)", flush=True)
            return data
    except Exception as e:
        print(f"ℹ️ Nu s-a putut descărca Master Index (se va crea unul nou): {e}", flush=True)

    return {"fisiere": {}, "last_updated": ""}


def salveaza_master_index(service, data):
    data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cale_temp = Path(NUME_MASTER_INDEX)
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name = '{NUME_MASTER_INDEX}' and trashed = false"
        list_params = get_list_params(q=query, fields="files(id)")
        res = service.files().list(**list_params).execute()
        files = res.get("files", [])

        media = MediaFileUpload(str(cale_temp), mimetype="application/json")

        if files:
            file_id = files[0]["id"]
            params = get_file_params(fileId=file_id)
            params["media_body"] = media
            service.files().update(**params).execute()
        else:
            file_metadata = {"name": NUME_MASTER_INDEX, "parents": [FOLDER_TEMP_INDEXES_ID]}
            params = get_file_params()
            params["body"] = file_metadata
            params["media_body"] = media
            service.files().create(**params).execute()

        print(f"💾 Master Index actualizat pe Drive! ({len(data['fisiere']):,} fișiere unice)", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()
    except Exception as e:
        print(f"❌ Eroare la salvarea Master Index: {e}", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()


# ==============================================================================
# SCANARE ȘI RECONSTRUCȚIE INDEX (FULL RE-INDEX)
# ==============================================================================
def executa_full_reindex(service):
    print("\n🚀 Reconstrucție completă index (FULL RE-INDEX)...", flush=True)
    master_data = {"fisiere": {}, "last_updated": ""}
    total_fisiere_scanate = 0
    timp_start = time.time()

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, 1):
        print(f"📂 [{idx}/{len(FOLDERE_XML_IDS)}] Scanare Shared Drive Folder ID: {folder_id}...", flush=True)
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            for incercare in range(5):
                try:
                    list_params = get_list_params(
                        q=query,
                        fields="nextPageToken, files(id, name)",
                        pageToken=page_token,
                        pageSize=1000,
                    )
                    response = service.files().list(**list_params).execute()
                    break
                except (socket.error, HttpError, Exception) as e:
                    print(f"⚠️ Rețea/Broken Pipe la scanare (încercarea {incercare + 1}/5): {e}", flush=True)
                    time.sleep(2 * (incercare + 1))
                    service = get_drive_service()  # Reîmprospătăm conexiunea API

            files = response.get("files", [])
            for f in files:
                nume = f["name"]
                total_fisiere_scanate += 1

                if nume not in master_data["fisiere"]:
                    master_data["fisiere"][nume] = {
                        "id": f["id"],
                        "folder_id": folder_id,
                        "downloaded": True,
                        "Tags_extracted": False,
                        "processed": False,
                    }

                if total_fisiere_scanate % 10000 == 0:
                    print(f"📊 [Status Update] Progres scanare: {total_fisiere_scanate:,} fișiere fizice parcurse...", flush=True)
                    salveaza_master_index(service, master_data)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    durata = round(time.time() - timp_start, 1)
    print(f"🏁 Reindexare completă finalizată! Total fișiere unice indexate: {len(master_data['fisiere']):,} ({durata}s)", flush=True)
    salveaza_master_index(service, master_data)
    return master_data


# ==============================================================================
# CURĂȚARE DUPLICATE MULTI-THREADED (BLINDATĂ ANTI-BROKEN PIPE)
# ==============================================================================
def curata_duplicate_multithreaded(service, master_data, max_workers=25):
    print("\n" + "=" * 60, flush=True)
    print(f"🚀 ÎNCEPERE CURĂȚARE TURBO MULTI-THREADED ({max_workers} FIRE PARALELE)...", flush=True)
    print("=" * 60, flush=True)

    fisiere_valide = master_data.get("fisiere", {})
    id_uri_oficiale = {meta["id"] for meta in fisiere_valide.values() if "id" in meta}

    print(f"🛡️ Total ID-uri oficiale protejate: {len(id_uri_oficiale):,}", flush=True)

    counter_lock = threading.Lock()
    total_duplicate_gunoi = 0
    total_fisiere_verificate = 0
    erori_gunoi = 0
    timp_start = time.time()

    def trashing_worker(file_id):
        nonlocal total_duplicate_gunoi, erori_gunoi
        # Fiecare thread își creează propriul client API izolat pentru a preveni conflictul de socket-uri
        thread_service = get_drive_service()

        for incercare in range(5):
            try:
                params = get_file_params(fileId=file_id)
                params["body"] = {"trashed": True}
                thread_service.files().update(**params).execute()

                with counter_lock:
                    total_duplicate_gunoi += 1
                    if total_duplicate_gunoi % 500 == 0:
                        durata = round(time.time() - timp_start, 1)
                        viteză = round(total_duplicate_gunoi / (durata if durata > 0 else 1), 1)
                        print(
                            f"⚡ [TURBO Trash] Mutate la coș #{total_duplicate_gunoi:,} fișiere... | Ritm: {viteză} fișiere/sec ({durata}s)",
                            flush=True,
                        )
                return True
            except (socket.error, HttpError, Exception) as e:
                # Dacă primim Broken Pipe sau Rate Limit, re-creăm serviciul și încercăm din nou
                if "429" in str(e) or "rateLimitExceeded" in str(e) or "Broken pipe" in str(e):
                    time.sleep(1.5 * (incercare + 1))
                    thread_service = get_drive_service()
                else:
                    time.sleep(0.5)

        with counter_lock:
            erori_gunoi += 1
        return False

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, 1):
        print(f"\n📂 [{idx}/{len(FOLDERE_XML_IDS)}] Scanare folder pentru curățare: {folder_id}...", flush=True)
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            response = None
            for incercare in range(5):
                try:
                    list_params = get_list_params(
                        q=query,
                        fields="nextPageToken, files(id, name)",
                        pageToken=page_token,
                        pageSize=1000,
                    )
                    response = service.files().list(**list_params).execute()
                    break
                except (socket.error, HttpError, Exception) as e:
                    print(f"⚠️ Rețea/Broken Pipe la citirea listei de curățare (încercarea {incercare + 1}/5): {e}", flush=True)
                    time.sleep(2 * (incercare + 1))
                    service = get_drive_service()

            if not response:
                print(f"❌ Nu s-a putut obține lista pentru folderul {folder_id}. Se trece la următorul.", flush=True)
                break

            files = response.get("files", [])
            total_fisiere_verificate += len(files)
            ids_de_sters = [f["id"] for f in files if f["id"] not in id_uri_oficiale]

            if ids_de_sters:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    executor.map(trashing_worker, ids_de_sters)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    durata_totala = round(time.time() - timp_start, 1)
    print("\n" + "=" * 60, flush=True)
    print(f"🏁 CURĂȚARE MULTI-THREADED FINALIZATĂ în {durata_totala}s!", flush=True)
    print(f"📊 Fișiere verificate: {total_fisiere_verificate:,}", flush=True)
    print(f"🗑️ Duplicate mutate în Trash: {total_duplicate_gunoi:,}", flush=True)
    if erori_gunoi > 0:
        print(f"⚠️ Erori întâmpinate la ștergere: {erori_gunoi:,}", flush=True)
    print("=" * 60 + "\n", flush=True)


# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def main():
    is_full = "--full" in sys.argv or os.getenv("IS_FULL", "").lower() in ["true", "1", "yes"]

    if is_full:
        print("🚀 [Strategie] Se execută FULL INDEX (Multi-Threaded Turbo Trash).", flush=True)
    else:
        print("ℹ️ [Strategie] Se execută verfificare standard.", flush=True)

    service = get_drive_service()
    master_data = executa_full_reindex(service)
    curata_duplicate_multithreaded(service, master_data, max_workers=25)


if __name__ == "__main__":
    main()
