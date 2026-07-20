import os
import sys
import json
import io
import re
import socket  # Protecție anti-freeze la nivel de rețea
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Setează un timeout global de 30 secunde pentru orice cerere de rețea
socket.setdefaulttimeout(30.0)

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

CALE_INDEX_LOCAL = "index_xml.json"

INDEX_FILE_ID = os.getenv("XML_STORAGE_INDEX", "").strip()
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES", "").replace('"', '').replace("'", "").strip()

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
        creds = service_account.Credentials.from_service_account_info(json.loads(github_secret), scopes=scopes)
    else:
        creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def descarca_index_existenta_din_drive(service):
    """Descărcare directă a indexului master prin ID-ul fix furnizat în XML_STORAGE_INDEX."""
    if os.path.exists(CALE_INDEX_LOCAL):
        return
    
    if not INDEX_FILE_ID:
        print("ℹ️ 'XML_STORAGE_INDEX' nu este setat. Se va începe un index nou local.", flush=True)
        return

    try:
        cerere = service.files().get_media(fileId=INDEX_FILE_ID, supportsAllDrives=True)
        fh = io.FileIO(CALE_INDEX_LOCAL, 'wb')
        downloader = MediaIoBaseDownload(fh, cerere)
        gata = False
        while not gata:
            _, gata = downloader.next_chunk()
        print(f"📥 [Cloud Sync] Încărcat 'index_xml.json' direct din Drive (ID: {INDEX_FILE_ID[:8]}...).", flush=True)
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca fișierul index folosind XML_STORAGE_INDEX: {e}", flush=True)


def salveaza_local_checkpoint(fisiere_map, informatii=""):
    """Salvare intermediară pe disc local + mesaj de progres concis."""
    acum_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    structura = {
        "last_updated": acum_iso,
        "total_fisiere": len(fisiere_map),
        "fisiere": fisiere_map
    }
    with open(CALE_INDEX_LOCAL, "w", encoding="utf-8") as f:
        json.dump(structura, f, ensure_ascii=False, indent=2)
    
    detaliu = f" ({informatii})" if informatii else ""
    print(f"💾 [Checkpoint Local] Total indexate: {len(fisiere_map)} fișiere unice{detaliu}.", flush=True)


def salveaza_final_in_drive(service, fisiere_map):
    """Upload-ul final master pe Google Drive la finalizarea completă a scanării."""
    salveaza_local_checkpoint(fisiere_map, informatii="Stare finală înainte de Upload")

    folder_destinatie_id = FOLDERE_XML_IDS[0] if FOLDERE_XML_IDS else None

    print(f"\n{GALBEN}📤 [Upload Drive] Se încarcă varianta finală a indexului pe Google Drive...{RESET}", flush=True)
    
    media = MediaFileUpload(CALE_INDEX_LOCAL, mimetype='application/json', resumable=True)

    # Încercare 1: Update direct pe ID-ul existent din variabilă
    if INDEX_FILE_ID:
        try:
            service.files().update(
                fileId=INDEX_FILE_ID,
                media_body=media,
                supportsAllDrives=True
            ).execute()
            print(f"{VERDE}✅ [Master Index Update Successful] Fișier sincronizat pe ID: {INDEX_FILE_ID}!{RESET}", flush=True)
            print(f"🔗 Link vizualizare: https://drive.google.com/file/d/{INDEX_FILE_ID}/view", flush=True)
            return
        except Exception as e:
            print(f"⚠️ ID-ul existent ({INDEX_FILE_ID}) nu este accesibil/valid: {e}. Se creează un fișier NOU...", flush=True)

    # Încercare 2: Creare fișier NOU pe Drive + Oferire Permisiuni de vizualizare
    try:
        file_metadata = {
            'name': 'index_xml.json',
            'parents': [folder_destinatie_id] if folder_destinatie_id else []
        }
        f_nou = service.files().create(
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True,
            fields='id'
        ).execute()
        
        id_nou = f_nou.get('id')

        try:
            service.permissions().create(
                fileId=id_nou,
                body={'type': 'anyone', 'role': 'reader'},
                supportsAllDrives=True
            ).execute()
        except Exception as perm_err:
            print(f"⚠️ Nu s-a putut seta permisiunea publică: {perm_err}", flush=True)

        print(f"\n{VERDE}======================================================================{RESET}", flush=True)
        print(f"{VERDE}🎉 Fișier nou 'index_xml.json' creat cu succes pe Google Drive!{RESET}", flush=True)
        print(f"{VERDE}👉 NOUL ID PENTRU VARIABILĂ ESTE: {id_nou}{RESET}", flush=True)
        print(f"{VERDE}🔗 LINK DIRECT PENTRU VIZUALIZARE: https://drive.google.com/file/d/{id_nou}/view{RESET}", flush=True)
        print(f"{VERDE}======================================================================{RESET}\n", flush=True)
    except Exception as create_err:
        print(f"{ROSU}❌ Eroare critică la crearea indexului pe Drive: {create_err}{RESET}", flush=True)


def curata_cos_de_gunoi_targetat(service):
    """Șterge definitiv fișierele din Trash aparținând celor 4 foldere."""
    print(f"\n{GALBEN}🧹 [Rutină Curățare] Verificare fișiere în Coșul de Gunoi (Trash)...{RESET}", flush=True)
    total_sterse = 0

    for idx_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        query = f"'{folder_id}' in parents and trashed = true"
        page_token = None
        sterse_folder = 0

        try:
            while True:
                response = service.files().list(
                    q=query,
                    spaces='drive',
                    fields='nextPageToken, files(id, name)',
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                files = response.get('files', [])
                if not files:
                    break

                for f in files:
                    try:
                        service.files().delete(fileId=f['id'], supportsAllDrives=True).execute()
                        sterse_folder += 1
                        total_sterse += 1
                    except Exception:
                        pass

                page_token = response.get('nextPageToken', None)
                if not page_token:
                    break

            if sterse_folder > 0:
                print(f"   🗑️ Folder {folder_id[:8]}: Eliminat definitiv {sterse_folder} fișiere din Trash.", flush=True)

        except Exception as e:
            print(f"   ⚠️ Folder {folder_id[:8]}: Eroare la scanarea Trash-ului: {e}", flush=True)

    if total_sterse > 0:
        print(f"{VERDE}✅ [Curățare Finalizată] Eliberate {total_sterse} noduri din Coșul de Gunoi!{RESET}", flush=True)


def aplica_si_curata_indexuri_temporare(service, fisiere_map):
    if not FOLDER_TEMP_INDEXES_ID:
        return fisiere_map

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
            return fisiere_map

        loguri_temp.sort(key=lambda x: x.get('createdTime', ''))
        print(f"\n{GALBEN}🔄 [Consolidare Mutații] Găsite {len(loguri_temp)} indexuri temporare în Drive. Se aplică cronologic...{RESET}", flush=True)

        for log_file in loguri_temp:
            file_id = log_file['id']
            file_name = log_file['name']
            
            try:
                content_bytes = service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
                data_log = json.loads(content_bytes.decode('utf-8'))
                flag_updates = data_log.get('flag_updates', {})
                numar_updateuri = 0

                for nume_f, modi_flags in flag_updates.items():
                    if isinstance(modi_flags, dict):
                        if modi_flags.get("_deleted") is True:
                            if nume_f in fisiere_map:
                                del fisiere_map[nume_f]
                                numar_updateuri += 1
                        else:
                            if nume_f in fisiere_map:
                                for key, val in modi_flags.items():
                                    fisiere_map[nume_f][key] = val
                                numar_updateuri += 1

                service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
                print(f"   └─ ✅ Aplicat și șters din Drive: {file_name} ({numar_updateuri} mutații procesate)", flush=True)

            except Exception as item_err:
                print(f"   └─ ⚠️ Eroare la procesarea fișierului temporar {file_name}: {item_err}", flush=True)

    except Exception as e:
        print(f"⚠️ Eroare la parcurgerea folderului de indexuri temporare: {e}", flush=True)

    return fisiere_map


def construieste_sau_actualizeaza_index():
    service = get_drive_service()
    
    descarca_index_existenta_din_drive(service)
    curata_cos_de_gunoi_targetat(service)
    
    pune_reset = os.getenv("STRATEGIE_RESET", "false").lower() == "true"
    
    fisiere_map = {}
    last_updated = None

    if os.path.exists(CALE_INDEX_LOCAL) and not pune_reset:
        try:
            with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
                data_stocata = json.load(f)
                if isinstance(data_stocata, dict) and "fisiere" in data_stocata:
                    last_updated = data_stocata.get("last_updated")
                    if isinstance(data_stocata["fisiere"], dict):
                        fisiere_map = data_stocata["fisiere"]
                    print(f"🧠 [Index Incremental] Încărcate {len(fisiere_map)} fișiere unice din master. Ultimul update: {last_updated}", flush=True)
        except Exception as e:
            print(f"⚠️ Eroare la citirea indexului vechi: {e}", flush=True)
    else:
        print(f"🚀 [FULL INDEX] Se construiește indexul complet de la zero...", flush=True)

    pattern_nume = re.compile(r"brut_legislatie_(\d+)_pag(\d+)\.xml")

    # STEP 1: Scanăm cele 4 foldere de XML
    for idx_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n{GALBEN}📂 Scanare Folder XML {idx_folder}/{len(FOLDERE_XML_IDS)} (ID: {folder_id[:8]}...){RESET}", flush=True)
        
        page_token = None
        contor_folder = 0
        fisiere_noi_in_folder = 0
        
        if last_updated and not pune_reset:
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_' and modifiedTime > '{last_updated}' and trashed = false"
        else:
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_' and trashed = false"
            
        try:
            while True:
                response = service.files().list(
                    q=query,
                    spaces='drive',
                    fields='nextPageToken, files(id, name)',
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                files = response.get('files', [])
                if not files:
                    break

                for f in files:
                    nume = f['name']
                    if nume not in fisiere_map:
                        fisiere_noi_in_folder += 1

                    match = pattern_nume.search(nume)
                    an_val = int(match.group(1)) if match else None
                    pag_val = int(match.group(2)) if match else None

                    stare_tags_existenta = fisiere_map.get(nume, {}).get("Tags_extracted", False)

                    fisiere_map[nume] = {
                        'id': f['id'],
                        'folder_id': folder_id,
                        'an': an_val,
                        'pagina': pag_val,
                        'Tags_extracted': stare_tags_existenta
                    }
                    
                    contor_folder += 1

                    # Salvăm și logăm doar la fiecare 10.000 de fișiere scanate per folder
                    if contor_folder % 10000 == 0:
                        salveaza_local_checkpoint(fisiere_map, informatii=f"Folder {idx_folder}: {contor_folder} scanate")

                page_token = response.get('nextPageToken', None)
                if not page_token:
                    break
                    
            print(f"✅ [Folder Finalizat] Scanate {contor_folder} fișiere în folderul {folder_id[:8]} (Fișiere noi adăugate: {fisiere_noi_in_folder}).", flush=True)

        except Exception as e:
            print(f"{ROSU}⚠️ Eroare scanare folder {folder_id[:8]}: {e}{RESET}", flush=True)

    # STEP 2: Aplicăm toate actualizările din folderul TEMPORARY_XML_INDEXES
    fisiere_map = aplica_si_curata_indexuri_temporare(service, fisiere_map)

    # STEP 3: Upload-ul master în Drive
    salveaza_final_in_drive(service, fisiere_map)


if __name__ == "__main__":
    construieste_sau_actualizeaza_index()
