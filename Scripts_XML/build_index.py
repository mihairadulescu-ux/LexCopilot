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
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

from drive_config import (
    MASTER_INDEX_FILE_ID,
    FOLDER_TEMP_INDEXES_ID,
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API
# ==============================================================================
def get_drive_service():
    """Autentificare în Google Drive API folosind GOOGLE_SERVICE_ACCOUNT_JSON."""
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")

    if creds_json:
        try:
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare la citirea secretului JSON: {e}", flush=True)
            sys.exit(1)

    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare la citirea fișierului local service_account.json: {e}", flush=True)

    print("❌ Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


# ==============================================================================
# OPERAȚIUNI CU MASTER INDEX
# ==============================================================================
def descarca_master_index(service):
    """Descarcă index_xml.json din Google Drive în memorie."""
    print(f"📥 Descărcare conținut Master Index (ID: {MASTER_INDEX_FILE_ID})...", flush=True)
    try:
        request = service.files().get_media(**get_file_params(fileId=MASTER_INDEX_FILE_ID))
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        fh.seek(0)
        continut = fh.read().decode("utf-8")
        master_data = json.loads(continut)
        print(f"✅ [Master Index] Încărcate {len(master_data.get('fisiere', {}))} fișiere.", flush=True)
        return master_data
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca Master Index-ul (posibil fișier nou sau eroare): {e}", flush=True)
        return {"fisiere": {}, "last_updated": ""}


def salveaza_master_index(service, master_data):
    """Suprascrie Master Index-ul (index_xml.json) pe Google Drive."""
    master_data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cale_temp = "/tmp/index_xml.json" if os.name != "nt" else "index_xml.json"

    with open(cale_temp, "w", encoding="utf-8") as f:
        json.dump(master_data, f, ensure_ascii=False, indent=2)

    try:
        media = MediaFileUpload(cale_temp, mimetype="application/json", resumable=True)
        updated_file = (
            service.files()
            .update(**get_file_params(fileId=MASTER_INDEX_FILE_ID, media_body=media))
            .execute()
        )
        print(f"✅ Master Index actualizat pe Drive cu succes! (ID: {updated_file.get('id')})", flush=True)
    except Exception as e:
        print(f"❌ Eroare la salvarea Master Index-ului pe Drive: {e}", flush=True)
    finally:
        if os.path.exists(cale_temp):
            os.remove(cale_temp)


# ==============================================================================
# EXECUȚIE STRATEGII
# ==============================================================================
def executa_full_index(service):
    """Scanează integral toate folderele și reconstruiește Master Index-ul."""
    print("🚀 Reconstrucție completă index (FULL INDEX)...", flush=True)
    master_data = {"fisiere": {}, "last_updated": ""}
    pattern_xml = re.compile(r"brut_legislatie_(\d{4})_pag(\d+)\.xml")

    total_fisiere = 0
    for folder_id in FOLDERE_XML_IDS:
        print(f"📂 Scanare folder Shared Drive ID: {folder_id[:8]}...", flush=True)
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            try:
                response = (
                    service.files()
                    .list(
                        **get_list_params(
                            q=query,
                            fields="nextPageToken, files(id, name, parents)",
                            pageToken=page_token,
                            pageSize=1000,
                        )
                    )
                    .execute()
                )

                files = response.get("files", [])
                for f in files:
                    nume = f["name"]
                    m = pattern_xml.search(nume)
                    if m:
                        an = int(m.group(1))
                        pag = int(m.group(2))
                        master_data["fisiere"][nume] = {
                            "id": f["id"],
                            "folder_id": folder_id,
                            "an": an,
                            "pagina": pag,
                            "downloaded": True,
                            "Tags_extracted": False,
                            "processed": False,
                        }
                        total_fisiere += 1

                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Eroare la scanarea paginii din folderul {folder_id[:8]}: {e}", flush=True)
                break

    print(f"📊 Reindexare completă finalizată. Total fișiere identificate: {total_fisiere}", flush=True)
    salveaza_master_index(service, master_data)


def executa_incremental_index(service):
    """Consolidează micro-indecșii temporari în Master Index."""
    print("⚡ Consolidare incrementală index...", flush=True)
    master_data = descarca_master_index(service)
    fisiere_dict = master_data.get("fisiere", {})

    query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"

    try:
        response = (
            service.files()
            .list(**get_list_params(q=query, fields="files(id, name)"))
            .execute()
        )
        temp_files = response.get("files", [])

        if not temp_files:
            print("ℹ️ Nu există micro-indecși temporari de consolidat.", flush=True)
            return

        print(f"🧩 Găsiți {len(temp_files)} micro-indecși de consolidat...", flush=True)
        modificari = False

        for tf in temp_files:
            file_id = tf["id"]
            nume_temp = tf["name"]

            try:
                request = service.files().get_media(**get_file_params(fileId=file_id))
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

                fh.seek(0)
                sub_data = json.loads(fh.read().decode("utf-8"))
                flag_updates = sub_data.get("flag_updates", {})

                for nume_xml, meta in flag_updates.items():
                    fisiere_dict[nume_xml] = meta
                    modificari = True

                service.files().delete(**get_file_params(fileId=file_id)).execute()
                print(f"   └─ Consolidat și șters micro-index: {nume_temp}", flush=True)

            except Exception as ex:
                print(f"⚠️ Eroare procesare micro-index {nume_temp}: {ex}", flush=True)

        if modificari:
            master_data["fisiere"] = fisiere_dict
            salveaza_master_index(service, master_data)

    except Exception as e:
        print(f"❌ Eroare la consolidarea incrementală: {e}", flush=True)


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
def main():
    is_full = "--full" in sys.argv or os.getenv("FORCE_FULL_INDEX", "").lower() == "true"

    if is_full:
        print("🚀 [Strategie] Se execută FULL INDEX (Reindexare completă).", flush=True)
    else:
        print("⚡ [Strategie] Se execută INCREMENTAL INDEX (Delta & Consolidare).", flush=True)

    service = get_drive_service()

    if is_full:
        executa_full_index(service)
    else:
        executa_incremental_index(service)


if __name__ == "__main__":
    main()
