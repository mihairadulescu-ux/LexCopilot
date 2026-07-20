import os
import sys
import json
import io
import time
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

CALE_INDEX_LOCAL = "index_xml.json"
NUME_INDEX_DRIVE = "index_xml.json"

# ID-uri configurare mediu
INDEX_FILE_ID = os.getenv("XML_STORAGE_INDEX", "").strip()
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES", "").replace('"', '').replace("'", "").strip() or "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"
FOLDER_METADATE_ID = os.getenv("METADATA_FOLDER_ID", "").strip() or "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"

FOLDERE_XML_RAW = os.getenv("DRIVE_FOLDER_XML", "").replace('"', '').replace("'", "").replace("\n", "").replace("\r", "")
FOLDERE_XML_IDS = [fid.strip() for fid in FOLDERE_XML_RAW.split(",") if fid.strip()] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
]


def get_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul '{credentials_path}'!")
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def descarca_index_master(service):
    """Descărcare Master Index din Drive cu fallback pe căutare dinamică."""
    target_id = INDEX_FILE_ID

    if not target_id or target_id == "1OkPgwX_F6FKwupuhD9kO3rynj4zdel0N":
        try:
            query = f"'{FOLDER_METADATE_ID}' in parents and name = '{NUME_INDEX_DRIVE}' and trashed = false"
            res = service.files().list(q=query, spaces='drive', fields='files(id)', supportsAllDrives=True).execute()
            files = res.get('files', [])
            if files:
                target_id = files[0]['id']
        except Exception as e:
            print(f"⚠️ Căutare dinamică index eșuată: {e}", flush=True)

    if not target_id:
        print("ℹ️ Zero Master Index identificat. Se începe cu o structură nouă.", flush=True)
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}, None

    try:
        cerere = service.files().get_media(fileId=target_id, supportsAllDrives=True)
        fh = io.FileIO(CALE_INDEX_LOCAL, 'wb')
        downloader = MediaIoBaseDownload(fh, cerere)
        gata = False
        while not gata:
            _, gata = downloader.next_chunk()

        with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"📥 [Cloud Sync] Încărcat '{NUME_INDEX_DRIVE}' din Drive (ID: {target_id[:8]}...).", flush=True)
            return data, target_id
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca indexul master din Drive: {e}", flush=True)
        return {"last_updated": None, "total_fisiere": 0, "fisiere": {}}, target_id


def aplica_micro_indecsi_si_curata(service, fisiere_master):
    """
    Citește, aplică și ȘTERGE micro-indecșii temporari din TEMPORARY_XML_INDEXES.
    Include tratare defensivă pentru fișierele șterse/inexistente (HTTP 404).
    """
    if not FOLDER_TEMP_INDEXES_ID:
        return fisiere_master, 0

    query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
    try:
        resp = service.files().list(
            q=query,
            fields="files(id, name, createdTime)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        loguri_temp = resp.get('files', [])
        if not loguri_temp:
            print("ℹ️ Nu există micro-indecși temporari de consolidat.", flush=True)
            return fisiere_master, 0

        # Sortăm cronologic pentru aplicare ordonată
        loguri_temp.sort(key=lambda x: x.get('createdTime', ''))
        print(f"🔄 [Consolidare Mutații] Găsite {len(loguri_temp)} indexuri temporare în Drive. Se aplică...", flush=True)

        mutații_aplicate = 0
        for log_file in loguri_temp:
            file_id = log_file['id']
            file_name = log_file.get('name', file_id)

            try:
                cerere = service.files().get_media(fileId=file_id, supportsAllDrives=True)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, cerere)
                gata = False
                while not gata:
                    _, gata = downloader.next_chunk()

                data_log = json.loads(fh.getvalue().decode('utf-8'))
                flag_updates = data_log.get('flag_updates', {})

                for nume_f, modi_flags in flag_updates.items():
                    if isinstance(modi_flags, dict):
                        if modi_flags.get("_deleted") is True:
                            if nume_f in fisiere_master:
                                del fisiere_master[nume_f]
                                mutații_aplicate += 1
                        else:
                            if nume_f in fisiere_master:
                                fisiere_master[nume_f].update(modi_flags)
                            else:
                                fisiere_master[nume_f] = modi_flags
                            mutații_aplicate += 1

                # Curățăm micro-indexul temporar procesat
                try:
                    service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
                except Exception:
                    pass

            except HttpError as err:
                # 🛡️ TRATARE DEFENSIVĂ 404: Fișierul a fost deja șters/mutat de un alt job
                if err.resp.status in [404, 410]:
                    continue
                print(f"   └─ ⚠️ Eroare procesare temporar {file_name}: {err}", flush=True)
            except Exception as e:
                print(f"   └─ ⚠️ Eroare neașteptată temporar {file_name}: {e}", flush=True)

        print(f"   └─ ✅ Consolidate cu succes {mutații_aplicate} mutații în baza master.", flush=True)
        return fisiere_master, mutații_aplicate

    except Exception as e:
        print(f"⚠️ Eroare la consolidarea micro-indecșilor: {e}", flush=True)
        return fisiere_master, 0


def salveaza_index_master(service, data_master, target_id):
    """Salvează și urcă indexul master actualizat în Google Drive."""
    data_master["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data_master["total_fisiere"] = len(data_master.get("fisiere", {}))

    with open(CALE_INDEX_LOCAL, "w", encoding="utf-8") as f:
        json.dump(data_master, f, ensure_ascii=False, indent=2)

    media = MediaFileUpload(CALE_INDEX_LOCAL, mimetype='application/json', resumable=True)

    try:
        if target_id:
            service.files().update(fileId=target_id, media_body=media, supportsAllDrives=True).execute()
            print(f"{VERDE}✅ Master Index actualizat pe Drive (ID: {target_id}){RESET}", flush=True)
        else:
            file_metadata = {'name': NUME_INDEX_DRIVE, 'parents': [FOLDER_METADATE_ID]}
            f_nou = service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True, fields='id').execute()
            print(f"{VERDE}🎉 Master Index creat de la zero pe Drive (ID: {f_nou.get('id')}){RESET}", flush=True)
    except Exception as e:
        print(f"{ROSU}❌ Eroare la salvarea Master Index pe Drive: {e}{RESET}", flush=True)


def main():
    print(f"\n{GALBEN}⚡ [Strategie] Se execută INCREMENTAL INDEX (Delta & Consolidare).{RESET}\n", flush=True)
    
    service = get_drive_service()
    data_master, target_id = descarca_index_master(service)
    fisiere_master = data_master.get("fisiere", {})

    print(f"🧠 [Index Incremental] Încărcate {len(fisiere_master)} fișiere unice din master.", flush=True)

    # 1. Consolidare micro-indecși temporari din TEMPORARY_XML_INDEXES
    fisiere_master, mutatii = aplica_micro_indecsi_si_curata(service, fisiere_master)

    # 2. Salvare finală Master Index pe Drive
    data_master["fisiere"] = fisiere_master
    salveaza_index_master(service, data_master, target_id)


if __name__ == "__main__":
    main()
