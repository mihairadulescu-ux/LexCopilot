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
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError
import io

from drive_config import (
    FOLDER_TEMP_INDEXES_ID,
    get_file_params,
    get_list_params,
)

# Folderul de PDF-uri pentru Monitoare Oficiale
DRIVE_FOLDER_PDF_ID = "1gRh-rWe32RNJU2PmN67XoFvkaCSotTA1"
NUME_MASTER_INDEX_MO = "index_monitoare.json"


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API (CU RECONECTARE ȘI TIMEOUT)
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
# SALVARE MASTER INDEX MO PENTRU SHARED DRIVES
# ==============================================================================
def salveaza_master_index_mo(service, data):
    data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cale_temp = Path(NUME_MASTER_INDEX_MO)
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name = '{NUME_MASTER_INDEX_MO}' and trashed = false"
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
            file_metadata = {"name": NUME_MASTER_INDEX_MO, "parents": [FOLDER_TEMP_INDEXES_ID]}
            params = get_file_params()
            params["body"] = file_metadata
            params["media_body"] = media
            service.files().create(**params).execute()

        print(f"💾 Master Index MO actualizat pe Drive! ({len(data['fisiere']):,} fișiere unice)", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()
    except Exception as e:
        print(f"❌ Eroare la salvarea Master Index MO: {e}", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()


# ==============================================================================
# CURĂȚARE DUPLICATE MULTI-THREADED (BLINDATĂ ANTI-BROKEN PIPE)
# ==============================================================================
def curata_duplicate_mo(service, master_data, max_workers=15):
    print("\n" + "=" * 60, flush=True)
    print(f"🚀 ÎNCEPERE CURĂȚARE DUPLICATE MO ({max_workers} FIRE PARALELE)...", flush=True)
    print("=" * 60, flush=True)

    fisiere_valide = master_data.get("fisiere", {})
    id_uri_oficiale = {meta["id"] for meta in fisiere_valide.values() if "id" in meta}
    
    print(f"🛡️ Total ID-uri oficiale protejate: {len(id_uri_oficiale):,}", flush=True)

    counter_lock = threading.Lock()
    total_duplicate_gunoi = 0
    erori_gunoi = 0
    timp_start = time.time()

    def trashing_worker(file_id):
        nonlocal total_duplicate_gunoi, erori_gunoi
        thread_service = get_drive_service()
        
        for incercare in range(5):
            try:
                params = get_file_params(fileId=file_id)
                params["body"] = {"trashed": True}
                thread_service.files().update(**params).execute()
                
                with counter_lock:
                    total_duplicate_gunoi += 1
                    if total_duplicate_gunoi % 200 == 0:
                        durata = round(time.time() - timp_start, 1)
                        viteză = round(total_duplicate_gunoi / (durata if durata > 0 else 1), 1)
                        print(
                            f"⚡ [TURBO Trash MO] Mutate la coș #{total_duplicate_gunoi:,} fișiere... | Ritm: {viteză} fișiere/sec ({durata}s)",
                            flush=True,
                        )
                return True
            except (socket.error, HttpError, Exception) as e:
                if "429" in str(e) or "rateLimitExceeded" in str(e) or "Broken pipe" in str(e):
                    time.sleep(1.5 * (incercare + 1))
                    thread_service = get_drive_service()
                else:
                    time.sleep(0.5)

        with counter_lock:
            erori_gunoi += 1
        return False

    page_token = None
    query = f"'{DRIVE_FOLDER_PDF_ID}' in parents and trashed = false"

    while True:
        response = None
        for incercare in range(10):
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
                pauza = min(2 ** incercare, 30)
                print(f"⚠️ Rețea/Google Error la citirea duplicatelor ({incercare + 1}/10): {e}. Reîncercăm în {pauza}s...", flush=True)
                time.sleep(pauza)
                service = get_drive_service()

        if not response:
            print("❌ Eroare critică la citirea fișierelor pentru curățare! Se întrerupe pasul de cleanup.", flush=True)
            break

        files = response.get("files", [])
        ids_de_sters = [f["id"] for f in files if f["id"] not in id_uri_oficiale]

        if ids_de_sters:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                executor.map(trashing_worker, ids_de_sters)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    durata_totala = round(time.time() - timp_start, 1)
    print("\n" + "=" * 60, flush=True)
    print(f"🏁 CURĂȚARE MONITOARE OFICIALE FINALIZATĂ în {durata_totala}s!", flush=True)
    print(f"🗑️ Duplicate PDF mutate în Trash: {total_duplicate_gunoi:,}", flush=True)
    if erori_gunoi > 0:
        print(f"⚠️ Erori la ștergere: {erori_gunoi:,}", flush=True)
    print("=" * 60 + "\n", flush=True)


# ==============================================================================
# MAIN ENGINE (FULL RE-INDEX CU GARANȚIE ANTI-ȘTERGERE ACCIDENTALĂ)
# ==============================================================================
def main():
    print("============================================================", flush=True)
    print("🚀 FULL RE-INDEX & DUPLICATE CLEANUP - MONITOARE OFICIALE", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()
    
    # Întotdeauna reconstruim Master Index de la zero (FULL RE-INDEX)
    master_data = {"fisiere": {}, "last_updated": ""}

    total_fisiere_scanate = 0
    page_token = None
    query = f"'{DRIVE_FOLDER_PDF_ID}' in parents and trashed = false"
    scanare_complet_reusita = True

    print(f"📂 Scanare completă Shared Drive Folder MO: {DRIVE_FOLDER_PDF_ID}...", flush=True)

    while True:
        response = None
        # Mecanism de RETRY automat la erori 500, 502, 503 sau de rețea
        for incercare in range(10):
            try:
                list_params = get_list_params(
                    q=query,
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=1000,
                )
                response = service.files().list(**list_params).execute()
                break  # Scanare cu succes a paginii curente
            except (socket.error, HttpError, Exception) as e:
                pauza = min(2 ** incercare, 30)
                print(f"⚠️ Rețea/Google Error (încercarea {incercare + 1}/10): {e}. Reîncercare în {pauza}s...", flush=True)
                time.sleep(pauza)
                service = get_drive_service()

        # Dacă pagina nu a putut fi descărcată nici după 10 încercări, oprim indexarea și blocăm curățarea
        if not response:
            print("❌ CRITICAL ERROR: Scanarea nu a putut fi finalizată 100%! Curățarea este BLOCATĂ pentru siguranță.", flush=True)
            scanare_complet_reusita = False
            break

        files = response.get("files", [])
        for f in files:
            nume = f["name"]
            total_fisiere_scanate += 1
            
            # Primul fișier găsit cu acest nume devine cel oficial protejat
            if nume not in master_data["fisiere"]:
                master_data["fisiere"][nume] = {
                    "id": f["id"],
                    "name": nume,
                    "processed": False
                }

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    # Frâna de siguranță: Executăm curățarea NUMAI dacă scanarea a fost 100% completă
    if not scanare_complet_reusita:
        print("⛔ ABORT TRASH: Curățarea a fost anulată automat deoarece scanarea a întâmpinat blocaje neprevăzute.", flush=True)
        sys.exit(1)

    print(f"📊 Fișiere fizice parcurse: {total_fisiere_scanate:,}", flush=True)
    print(f"✅ Monitoare Oficiale unice identificate: {len(master_data['fisiere']):,}", flush=True)
    
    # Salvează indexul actualizat în Drive
    salveaza_master_index_mo(service, master_data)

    # Execută curățarea automată a duplicatelor pe 15 fire paralele
    curata_duplicate_mo(service, master_data, max_workers=15)


if __name__ == "__main__":
    main()
