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
# PASUL 0: INCARCARE SNAPSHOT VECHIUL INDEX PENTRU PRESERVARE FLAG-URI
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
# SALVARE MASTER INDEX SAU BACKUP INTERIMAR PE DRIVE
# ==============================================================================
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
            print(f"💾 {mesaj} salvat pe Drive cu succes! ({total_intrare:,} intrări)", flush=True)
            if cale_temp.exists():
                cale_temp.unlink()
            return True
        except Exception as e:
            print(f"⚠️ Eroare la salvarea indexului pe Drive (încercarea {incercare + 1}/5): {e}", flush=True)
            time.sleep(3)

    if cale_temp.exists():
        cale_temp.unlink()
    print("❌ CRITICAL: Nu s-a putut salva indexul pe Drive după 5 încercări!", flush=True)
    return False


# ==============================================================================
# EXECUȚIE TRASH MULTI-THREADED
# ==============================================================================
def executa_trash_multi_threaded(ids_de_sters, max_workers=15):
    if not ids_de_sters:
        print("✨ Nu există fișiere goale sau duplicate de șters! Totul este curat.", flush=True)
        return

    print("\n" + "=" * 60, flush=True)
    print(f"🚀 TRIMITERE LA COȘ #{len(ids_de_sters):,} FIȘIERE (<10B sau DUPLICATE) CU {max_workers} FIRE PARALELE...", flush=True)
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
    print(f"🗑️ Fișiere mutate în coș: {total_curatate:,}", flush=True)
    if erori_gunoi > 0:
        print(f"⚠️ Erori întâmpinate la ștergere: {erori_gunoi:,}", flush=True)
    print("=" * 60 + "\n", flush=True)


# ==============================================================================
# MAIN ENGINE: RAW SCAN WITH INCREMENTAL SAVES -> CLEANUP <10B -> SAVE FIRST -> TRASH
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

    # 2. Scanare fizică Cross-Drive cu Circuit Breaker și Salvare Incrementală la 10.000 fișiere
    for index_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n📂 [{index_folder}/{len(FOLDERE_XML_IDS)}] Scanare Drive XML Folder ID: {folder_id}...", flush=True)
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        seen_tokens = set()
        unice_la_ultimul_check = len(raw_inventory)
        fisiere_parcurse_folder = 0

        while True:
            if page_token in seen_tokens:
                print(f"⚠️ DETECTATĂ BUCLĂ REPETITIVĂ DE TOKEN! Oprim scanarea pe folderul {folder_id[:8]}.", flush=True)
                break
            if page_token:
                seen_tokens.add(page_token)

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
            
            if not files:
                break

            for f in files:
                nume = f["name"]
                total_fisiere_gasite += 1
                fisiere_de_la_ultimul_save += 1
                fisiere_parcurse_folder += 1
                
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

            # SALVARE INCREMENTALĂ LA FIECARE 10.000 DE FIȘIERE PARCURSE
            if fisiere_de_la_ultimul_save >= 10000:
                unice_curente = len(raw_inventory)
                fisiere_unice_noi = unice_curente - unice_la_ultimul_check
                fisiere_de_la_ultimul_save = 0
                unice_la_ultimul_check = unice_curente

                print(f"📊 [Progres Scanare RAW] {total_fisiere_gasite:,} parcurse total ({unice_curente:,} unice | +{fisiere_unice_noi:,} noi în ultimele 10k)...", flush=True)
                
                # Salvare interimară de siguranță pe Drive
                salveaza_master_index_xml(
                    service, 
                    {"inventory": raw_inventory}, 
                    nume_fisier=NUME_MASTER_INDEX_XML, 
                    mesaj=f"Backup Interimar RAW Inventar ({total_fisiere_gasite:,} fișiere fizice)"
                )

                # CIRCUIT BREAKER
                if fisiere_parcurse_folder >= 20000 and fisiere_unice_noi < 50:
                    print(f"🛑 [CIRCUIT BREAKER] Folderul {folder_id[:8]} a atins limita de saturare (+{fisiere_unice_noi} unice noi la ultimele 10k parcurse). Trecem la folderul următor!", flush=True)
                    break

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    print(f"\n📊 SCANARE CROSS-DRIVE FINALIZATĂ!")
    print(f"📊 TOTAL FIȘIERE FIZICE PARCURSE PE CELE 4 DRIVE-URI: {total_fisiere_gasite:,}", flush=True)
    print(f"📊 GRUPURI DE NUME UNICE IDENTIFICATE: {len(raw_inventory):,}", flush=True)

    # ==========================================================================
    # 3. CONSOLIDARE ÎN MEMORIE, FILTRARE <10 BAȚI ȘI TRANSFER DE STARE (MERGE)
    # ==========================================================================
    print("\n" + "=" * 60, flush=True)
    print("🧠 ANALIZĂ, FILTRARE FIȘIERE GOALE (<10B) ȘI PRESERVARE FLAG-URI...", flush=True)
    print("=" * 60, flush=True)

    master_index = {"fisiere": {}, "total_fisiere": 0, "last_updated": ""}
    ids_de_sters = []
    stari_recuperate = 0
    fisiere_mici_eliminate = 0

    for nume_fisier, lista_variante in raw_inventory.items():
        # 1. Filtram mai intai variantele care au marimea mai mica de 10 bati
        variante_valide = [v for v in lista_variante if v["size"] >= 10]
        variante_mici = [v for v in lista_variante if v["size"] < 10]

        # Toate variantele sub 10 bati merg direct la cos!
        for v_mica in variante_mici:
            ids_de_sters.append(v_mica["id"])
            fisiere_mici_eliminate += 1

        # Daca nu exista nicio varianta >= 10 bati pentru acest nume, trecem mai departe
        if not variante_valide:
            continue

        # 2. Alegem castigatorul dintre variantele valide (dupa data crearii)
        if len(variante_valide) == 1:
            castigator = variante_valide[0]
        else:
            variante_valide.sort(key=lambda x: x["createdTime"], reverse=True)
            castigator = variante_valide[0]
            
            # Restul variantelor valide sunt duplicate si merg la cos
            for duplicat in variante_valide[1:]:
                ids_de_sters.append(duplicat["id"])

        # 3. Preluăm starea veche (flag-urile de prelucrare)
        vechea_stare = old_index_map.get(nume_fisier, {})
        if vechea_stare:
            stari_recuperate += 1

        master_index["fisiere"][nume_fisier] = {
            "id": castigator["id"],
            "folder_id": castigator["folder_id"],
            "createdTime": castigator["createdTime"],
            "size": castigator["size"],
            "downloaded": vechea_stare.get("downloaded", True),
            "Tags_extracted": vechea_stare.get("Tags_extracted", False),
            "processed": vechea_stare.get("processed", False)
        }

        for cheie, valoare in vechea_stare.items():
            if cheie not in master_index["fisiere"][nume_fisier]:
                master_index["fisiere"][nume_fisier][cheie] = valoare

    master_index["total_fisiere"] = len(master_index["fisiere"])

    print(f"✅ Fișiere XML validate drept MASTER (>=10B): {master_index['total_fisiere']:,}", flush=True)
    print(f"🛡️ Stări/Flag-uri de procesare conservate din indexul vechi: {stari_recuperate:,}", flush=True)
    print(f"🗑️ Fișiere goale/corupte (<10B) identificate pentru eliminare: {fisiere_mici_eliminate:,}", flush=True)
    print(f"🗑️ Total ID-uri trimise la coș (goale + duplicate): {len(ids_de_sters):,}", flush=True)

    # ==========================================================================
    # 4. SALVĂM MASTER INDEX-UL FINAL PE DRIVE *ÎNAINTE* DE TRASH!
    # ==========================================================================
    print("\n" + "=" * 60, flush=True)
    print("💾 SALVARE MASTER INDEX FINAL PE GOOGLE DRIVE (PRE-TRASH)...", flush=True)
    print("=" * 60, flush=True)
    
    salvat_cu_succes = salveaza_master_index_xml(
        service, 
        master_index, 
        nume_fisier=NUME_MASTER_INDEX_XML, 
        mesaj="Master Index XML Final Curat (Pre-Trash)"
    )

    if not salvat_cu_succes:
        print("❌ ABORT: Nu s-a putut salva indexul final pe Drive. Se oprește ștergerea pentru siguranță.", flush=True)
        sys.exit(1)

    # ==========================================================================
    # 5. TRIMITEM FIȘIERELE GOALE ȘI DUPLICATELE LA COȘ (DUPĂ SALVAREA INDEXULUI)
    # ==========================================================================
    if ids_de_sters:
        executa_trash_multi_threaded(ids_de_sters, max_workers=15)

    print("\n============================================================", flush=True)
    print("🎉 PROCESUL DE REINDEXARE COMPLETĂ ȘI CURĂȚARE S-A ÎNCHEIAT CU SUCCES!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
