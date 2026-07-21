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
    FOLDER_TEMP_INDEXES_ID,
    get_file_params,
    get_list_params,
)

# Folderul de PDF-uri pentru Monitoare Oficiale
DRIVE_FOLDER_PDF_ID = "1gRh-rWe32RNJU2PmN67XoFvkaCSotTA1"
NUME_MASTER_INDEX_MO = "index_monitoare.json"


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
# SALVARE MASTER INDEX SAU DRAFT INDEX PE DRIVE
# ==============================================================================
def salveaza_master_index_mo(service, data, nume_fisier=NUME_MASTER_INDEX_MO, mesaj="Master Index MO"):
    data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cale_temp = Path(nume_fisier)
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        query = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name = '{nume_fisier}' and trashed = false"
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
            file_metadata = {"name": nume_fisier, "parents": [FOLDER_TEMP_INDEXES_ID]}
            params = get_file_params()
            params["body"] = file_metadata
            params["media_body"] = media
            service.files().create(**params).execute()

        print(f"💾 {mesaj} actualizat pe Drive! ({len(data.get('inventory', data.get('fisiere', {}))):,} intrări)", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()
    except Exception as e:
        print(f"❌ Eroare la salvarea indexului: {e}", flush=True)
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
    print(f"🚀 TRIMITERE LA COȘ #{len(ids_de_sters):,} DUPLICATE ({max_workers} FIRE PARALELE)...", flush=True)
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
                            f"⚡ [TURBO Trash MO] Mutate la coș #{total_curatate:,}/{len(ids_de_sters):,} | Ritm: {viteza} f/sec ({durata}s)",
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
    print(f"🗑️ Duplicate mutate în coș: {total_curatate:,}", flush=True)
    if erori_gunoi > 0:
        print(f"⚠️ Erori întâmpinate la ștergere: {erori_gunoi:,}", flush=True)
    print("=" * 60 + "\n", flush=True)


# ==============================================================================
# MAIN ENGINE: PERSISTENT SCANNING WITH INCREMENTAL DRIVE BACKUPS
# ==============================================================================
def main():
    print("============================================================", flush=True)
    print("🚀 FULL RAW INVENTORY & ANALYTICAL CLEANUP - MONITOARE OFICIALE", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()
    
    raw_inventory = {}
    total_fisiere_gasite = 0
    fisiere_de_la_ultimul_save = 0
    page_token = None
    query = f"'{DRIVE_FOLDER_PDF_ID}' in parents and trashed = false"

    print(f"📂 Scanare RAW pe Shared Drive Folder MO: {DRIVE_FOLDER_PDF_ID}...", flush=True)

    while True:
        response = None
        incercare = 0

        # BUCLĂ DE RETRY PERSISTENTĂ PE PAGINĂ (Nu sare nicio pagină la erori de socket)
        while True:
            try:
                list_params = get_list_params(
                    q=query,
                    fields="nextPageToken, files(id, name, createdTime, size)",
                    pageToken=page_token,
                    pageSize=1000,
                )
                response = service.files().list(**list_params).execute()
                break  # Pagina descarcata cu succes
            except (socket.error, socket.timeout, HttpError, Exception) as e:
                incercare += 1
                pauza = min(2 ** incercare, 30)
                print(f"⚠️ Connection Error pe pageToken ({incercare}): {e}. Pauză {pauza}s și reîncercăm de la același punct...", flush=True)
                time.sleep(pauza)
                service = get_drive_service()

        files = response.get("files", [])
        for f in files:
            nume = f["name"]
            total_fisiere_gasite += 1
            fisiere_de_la_ultimul_save += 1
            
            meta_item = {
                "id": f["id"],
                "createdTime": f.get("createdTime", "1970-01-01T00:00:00.000Z"),
                "size": int(f.get("size", 0))
            }

            if nume not in raw_inventory:
                raw_inventory[nume] = []
            raw_inventory[nume].append(meta_item)

        # SALVARE ÎN BUCĂȚI LA FIECARE 10.000 DE FIȘIERE
        if fisiere_de_la_ultimul_save >= 10000:
            fisiere_de_la_ultimul_save = 0
            print(f"📊 [Progres Scanare] {total_fisiere_gasite:,} fișiere fizice colectate...", flush=True)
            salveaza_master_index_mo(
                service, 
                {"inventory": raw_inventory}, 
                nume_fisier=NUME_MASTER_INDEX_MO, 
                mesaj=f"Backup Interimar ({total_fisiere_gasite:,} fișiere)"
            )

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    print(f"\n📊 SCANARE FINALIZATĂ!")
    print(f"📊 TOTAL FIȘIERE FIZICE PARCURSE: {total_fisiere_gasite:,}", flush=True)
    print(f"📊 GRUPURI DE NUME UNICE IDENTIFICATE: {len(raw_inventory):,}", flush=True)

    # ==========================================================================
    # CONSOLIDARE ÎN MEMORIE (SORTARE & SELECȚIE MASTER)
    # ==========================================================================
    print("\n" + "=" * 60, flush=True)
    print("🧠 ANALIZĂ ȘI SORTARE ÎN MEMORIE PENTRU CURĂȚARE...", flush=True)
    print("=" * 60, flush=True)

    master_index = {"fisiere": {}, "last_updated": ""}
    ids_de_sters = []

    for nume_fisier, lista_variante in raw_inventory.items():
        if len(lista_variante) == 1:
            castigator = lista_variante[0]
        else:
            # Sortare: preferă dimensiune > 0 și cel mai recent createdTime
            lista_variante.sort(
                key=lambda x: (x["size"] > 0, x["createdTime"]), 
                reverse=True
            )
            castigator = lista_variante[0]
            
            for duplicat in lista_variante[1:]:
                ids_de_sters.append(duplicat["id"])

        master_index["fisiere"][nume_fisier] = {
            "id": castigator["id"],
            "name": nume_fisier,
            "createdTime": castigator["createdTime"],
            "size": castigator["size"],
            "processed": False
        }

    print(f"✅ Fișiere validate drept MASTER (de păstrat): {len(master_index['fisiere']):,}", flush=True)
    print(f"🗑️ Duplicate identificate pentru eliminare: {len(ids_de_sters):,}", flush=True)

    # Pasul 1: Trimitem la coș duplicatele identificate
    if ids_de_sters:
        executa_trash_multi_threaded(ids_de_sters, max_workers=15)

    # Pasul 2: Salvăm varianta finală, curată și consolidată a Master Index-ului
    salveaza_master_index_mo(
        service, 
        master_index, 
        nume_fisier=NUME_MASTER_INDEX_MO, 
        mesaj="Master Index MO Final Curat"
    )


if __name__ == "__main__":
    main()
