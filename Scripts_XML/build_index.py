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
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

try:
    import XML_INDEX_READER
except ImportError:
    from Scripts_XML import XML_INDEX_READER


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API
# ==============================================================================
def get_drive_service():
    """Autentificare în Google Drive API folosind GOOGLE_SERVICE_ACCOUNT_JSON."""
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
# OPERAȚIUNI CU MASTER INDEX (DELEGAT CĂTRE XML_INDEX_READER)
# ==============================================================================
def descarca_master_index(service):
    """Descarcă index_xml.json din Google Drive în memorie."""
    print("📥 Descărcare conținut Master Index (index_xml.json)...", flush=True)
    try:
        if hasattr(XML_INDEX_READER, "descarca_index_master"):
            master_data = XML_INDEX_READER.descarca_index_master(service)
        else:
            master_data = XML_INDEX_READER.descarca_master_index(service)
        print(f"✅ [Master Index] Încărcate {len(master_data.get('fisiere', {}))} fișiere.", flush=True)
        return master_data
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca Master Index-ul (posibil fișier nou sau eroare): {e}", flush=True)
        return {"fisiere": {}, "last_updated": ""}


def salveaza_master_index(service, master_data):
    """Suprascrie Master Index-ul (index_xml.json) pe Google Drive."""
    master_data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        if hasattr(XML_INDEX_READER, "salveaza_master_index"):
            res = XML_INDEX_READER.salveaza_master_index(service, master_data)
        elif hasattr(XML_INDEX_READER, "salveaza_index_master"):
            res = XML_INDEX_READER.salveaza_index_master(service, master_data)
        else:
            res = None

        if res:
            print(f"💾 [CHECKPOINT] Master Index actualizat pe Drive! ({len(master_data['fisiere']):,} fișiere unice)", flush=True)
        else:
            print(f"💾 Master Index actualizat pe Drive! ({len(master_data['fisiere']):,} fișiere unice)", flush=True)
    except Exception as e:
        print(f"❌ Excepție la salvarea Master Index-ului pe Drive: {e}", flush=True)


# ==============================================================================
# CURĂȚARE DUPLICATE / FIȘIERE NEINDEXATE FOLOSIND BATCH REQUESTS (ULTRA-RAPID)
# ==============================================================================
def curata_duplicate_drive(service, master_data):
    """
    Scanează folderele Shared Drive și mută în Trash fișierele fizice neindexate
    folosind BATCH HTTP REQUESTS (pachete de 100 de cereri într-un singur apel).
    """
    print("\n" + "=" * 60, flush=True)
    print("⚡ ÎNCEPERE ETAPĂ MUTARE ULTRA-RAPIDĂ ÎN TRASH (BATCH API)...", flush=True)
    print("=" * 60, flush=True)

    fisiere_valide = master_data.get("fisiere", {})
    id_uri_oficiale = {meta["id"] for meta in fisiere_valide.values() if "id" in meta}
    
    print(f"🛡️ Total ID-uri oficiale protejate în Master Index: {len(id_uri_oficiale):,}", flush=True)

    total_fisiere_verificate = 0
    total_duplicate_gunoi = 0
    erori_gunoi = 0
    timp_start = time.time()

    # Dimensiunea maximă recomandată pentru un pachet batch de la Google Drive API este 100
    LUNGIME_BATCH = 100

    def batch_callback(request_id, response, exception):
        nonlocal total_duplicate_gunoi, erori_gunoi
        if exception is not None:
            erori_gunoi += 1
        else:
            total_duplicate_gunoi += 1

    for folder_idx, folder_id in enumerate(FOLDERE_XML_IDS, 1):
        print(f"\n📂 [{folder_idx}/{len(FOLDERE_XML_IDS)}] Scanare folder pentru curățare batch: {folder_id[:8]}...", flush=True)
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            try:
                response = (
                    service.files()
                    .list(
                        **get_list_params(
                            q=query,
                            fields="nextPageToken, files(id, name)",
                            pageToken=page_token,
                            pageSize=1000,
                        )
                    )
                    .execute()
                )

                files = response.get("files", [])
                batch = service.new_batch_http_request(callback=batch_callback)
                fisiere_in_batch = 0

                for f in files:
                    total_fisiere_verificate += 1
                    file_id = f["id"]

                    # Dacă ID-ul fișierului NU este în Master Index, îl adăugăm în lotul batch curent
                    if file_id not in id_uri_oficiale:
                        params = get_file_params(fileId=file_id)
                        params["body"] = {"trashed": True}
                        
                        batch.add(service.files().update(**params))
                        fisiere_in_batch += 1

                        # Când lotul atinge 100 de fișiere, executăm întregul pachet dintr-o singură cerere
                        if fisiere_in_batch >= LUNGIME_BATCH:
                            batch.execute()
                            batch = service.new_batch_http_request(callback=batch_callback)
                            fisiere_in_batch = 0

                            # Afișăm progresul la fiecare 1.000 de fișiere procesate
                            if total_duplicate_gunoi > 0 and total_duplicate_gunoi % 1000 < LUNGIME_BATCH:
                                durata = round(time.time() - timp_start, 1)
                                viteză = round(total_duplicate_gunoi / (durata if durata > 0 else 1), 1)
                                print(
                                    f"🚀 [Batch Progress] Mutate la Trash: {total_duplicate_gunoi:,} fișiere | Ritm: {viteză} fișiere/sec ({durata}s)",
                                    flush=True,
                                )
                            time.sleep(0.1) # Micro-pauză între batch-uri pentru a respecta cotele per minut

                # Executăm restul de fișiere rămase în pachetul parțial
                if fisiere_in_batch > 0:
                    batch.execute()

                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Eroare la procesarea lotului din folderul {folder_id[:8]}: {e}", flush=True)
                time.sleep(1)
                break

    durata_totala = round(time.time() - timp_start, 1)
    print("\n" + "=" * 60, flush=True)
    print(f"🏁 CURĂȚARE BATCH FINALIZATĂ în {durata_totala}s!", flush=True)
    print(f"📊 Fișiere verificate: {total_fisiere_verificate:,}", flush=True)
    print(f"🗑️ Duplicate mutate în Trash: {total_duplicate_gunoi:,}", flush=True)
    if erori_gunoi > 0:
        print(f"⚠️ Erori întâmpinate în pachete: {erori_gunoi}", flush=True)
    print("=" * 60 + "\n", flush=True)


# ==============================================================================
# EXECUȚIE STRATEGII (FULL VS INCREMENTAL)
# ==============================================================================
def executa_full_index(service):
    """Scanează integral toate folderele, reconstruiește Master Index-ul și mută fișierele neindexate în Trash."""
    print("🚀 Reconstrucție completă index (FULL INDEX)...", flush=True)
    master_data = {"fisiere": {}, "last_updated": ""}
    pattern_xml = re.compile(r"brut_legislatie_(\d{4})_pag(\d+)\.xml")

    total_fisiere = 0
    ultimul_checkpoint = 0
    PAS_CHECKPOINT = 10000
    timp_start = time.time()

    for folder_idx, folder_id in enumerate(FOLDERE_XML_IDS, 1):
        print(f"📂 [{folder_idx}/{len(FOLDERE_XML_IDS)}] Scanare Shared Drive Folder ID: {folder_id[:8]}...", flush=True)
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

                        if total_fisiere - ultimul_checkpoint >= PAS_CHECKPOINT:
                            durata = round(time.time() - timp_start, 1)
                            print(
                                f"📊 [Status Update] Progres scanare: {total_fisiere:,} fișiere fizice parcurse...",
                                flush=True,
                            )
                            salveaza_master_index(service, master_data)
                            ultimul_checkpoint = total_fisiere

                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Eroare la scanarea paginii din folderul {folder_id[:8]}: {e}", flush=True)
                break

    durata_totala = round(time.time() - timp_start, 1)
    print(
        f"🏁 Reindexare completă finalizată! Total fișiere unice indexate: {len(master_data['fisiere']):,} (Timp total scanare: {durata_totala}s)",
        flush=True,
    )
    salveaza_master_index(service, master_data)

    # Executăm curățarea BATCH
    curata_duplicate_drive(service, master_data)


def executa_incremental_index(service):
    """Consolidează micro-indecșii temporari în Master Index."""
    print("⚡ Consolidare incrementală index...", flush=True)
    master_data = descarca_master_index(service)
    fisiere_dict = master_data.get("fisiere", {})

    folder_temp_id = getattr(XML_INDEX_READER, "FOLDER_TEMP_INDEXES_ID", None)
    if not folder_temp_id:
        from drive_config import FOLDER_TEMP_INDEXES_ID
        folder_temp_id = FOLDER_TEMP_INDEXES_ID

    query = f"'{folder_temp_id}' in parents and name contains 'temp_index_' and trashed = false"

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

                params_del = get_file_params(fileId=file_id)
                params_del["body"] = {"trashed": True}
                service.files().update(**params_del).execute()
                print(f"   └─ Consolidat și mutat în Trash micro-index: {nume_temp}", flush=True)

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
        print("🚀 [Strategie] Se execută FULL INDEX (Reindexare completă + Mutare fișiere neindexate în Trash BATCH).", flush=True)
    else:
        print("⚡ [Strategie] Se execută INCREMENTAL INDEX (Delta & Consolidare).", flush=True)

    service = get_drive_service()

    if is_full:
        executa_full_index(service)
    else:
        executa_incremental_index(service)


if __name__ == "__main__":
    main()
