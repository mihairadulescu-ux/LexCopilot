import os
import sys
import time
import json
import socket
import re
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
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

# MAPARE UNITARĂ PENTRU ID-UL MASTER INDEXULUI XML
INDEX_FILE_ID = (
    os.getenv("XML_STORAGE_INDEX")
    or os.getenv("INDEX_FILE_ID")
    or getattr(sys.modules.get("drive_config"), "XML_STORAGE_INDEX", None)
    or getattr(sys.modules.get("drive_config"), "INDEX_FILE_ID", None)
    or "1OkPgwX_F6FKwupuhD9kO3rynj4zdel0N"
)

NUME_MASTER_INDEX_XML = "index_xml.json"


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API
# ==============================================================================
def get_drive_service():
    """Creează un client Drive API robust cu timeout setat."""
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
# PASUL 0: ÎNCĂRCARE SNAPSHOT INDEX VECHI
# ==============================================================================
def incarca_snapshot_index_vechi(service):
    """Descarcă indexul existent pentru a-i păstra flag-urile de stare."""
    print(f"\n📦 [SNAPSHOT] Descărcare Index Vechi din Drive (ID: {INDEX_FILE_ID})...", flush=True)
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
# SALVARE MASTER INDEX PE DRIVE
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
# CURĂȚARE MICRO-INDECȘI TEMPORARI
# ==============================================================================
def curata_micro_indecsi_procesati(service):
    """Șterge fișierele temporare de micro-index (temp_index_*.json)."""
    try:
        query_temp = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
        res = service.files().list(**get_list_params(q=query_temp, fields="files(id, name)")).execute()
        files = res.get("files", [])

        if files:
            print(f"\n🧹 Curățare {len(files)} fișiere de micro-index temporare...", flush=True)
            for f in files:
                try:
                    params = get_file_params(fileId=f["id"])
                    params["body"] = {"trashed": True}
                    service.files().update(**params).execute()
                except Exception as e:
                    print(f"⚠️ Nu s-a putut șterge micro-indexul {f['name']}: {e}", flush=True)
            print("✅ Micro-indecșii temporari au fost curățați cu succes!", flush=True)
        else:
            print("\n✨ Nu există micro-indecși temporari de curățat.", flush=True)
    except Exception as e:
        print(f"⚠️ Eroare la curățarea micro-indecșilor: {e}", flush=True)


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
# MAIN ENGINE
# ==============================================================================
def main():
    print("============================================================", flush=True)
    print("🚀 FULL RAW INVENTORY & STATE PRESERVING CLEANUP - XML", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()
    
    # 1. Preluăm snapshot-ul cu vechile flag-uri de procesare
    old_index_map = incarca_snapshot_index_vechi(service)

    raw_inventory = {}
    total_fisiere_gasite = 0
    fisiere_de_la_ultimul_save = 0
    timp_start = time.time()

    # 2. Scanare fizică Cross-Drive
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

                # AFISARE RAPIDĂ DE PROGRES LIVE LA FIECARE 500 FIȘIERE CITITE
                if total_fisiere_gasite % 500 == 0:
                    durata_partiala = round(time.time() - timp_start, 1)
                    print(f"   ⏳ [LIVE] Scanate: {total_fisiere_gasite:,} fișiere fizice pe Drive ({durata_partiala}s)...", flush=True)

            if fisiere_de_la_ultimul_save >= 10000:
                unice_curente = len(raw_inventory)
                fisiere_unice_noi = unice_curente - unice_la_ultimul_check
                fisiere_de_la_ultimul_save = 0
                unice_la_ultimul_check = unice_curente

                print(f"📊 [Backup Interimar] {total_fisiere_gasite:,} parcurse total ({unice_curente:,} unice | +{fisiere_unice_noi:,} noi în ultimele 10k)...", flush=True)
                
                salveaza_master_index_xml(
                    service, 
                    {"inventory": raw_inventory}, 
                    nume_fisier=NUME_MASTER_INDEX_XML, 
                    mesaj=f"Backup Interimar RAW Inventar ({total_fisiere_gasite:,} fișiere fizice)"
                )

                if fisiere_parcurse_folder >= 20000 and fisiere_unice_noi < 50:
                    print(f"🛑 [CIRCUIT BREAKER] Folderul {folder_id[:8]} a atins limita de saturare. Trecem mai departe!", flush=True)
                    break

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    print(f"\n📊 SCANARE CROSS-DRIVE FINALIZATĂ!")
    print(f"📊 TOTAL FIȘIERE FIZICE PARCURSE: {total_fisiere_gasite:,}", flush=True)

    # ==========================================================================
    # 3. CONSOLIDARE SEMANTICĂ, FILTRARE <10B ȘI MERGE DE STARE
    # ==========================================================================
    print("\n" + "=" * 60, flush=True)
    print("🧠 ANALIZĂ SEMANTICĂ (AN_PAG), FILTRARE <10B ȘI PRESERVARE FLAG-URI...", flush=True)
    print("=" * 60, flush=True)

    pattern_xml = re.compile(r"^brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)
    
    grupuri_semantice = {}
    fisiere_mici_eliminate = 0
    ids_de_sters = []

    for nume_fisier, lista_variante in raw_inventory.items():
        match = pattern_xml.match(nume_fisier)
        if match:
            cheie_semantica = f"{match.group(1)}_pag{match.group(2)}"
        else:
            cheie_semantica = nume_fisier

        if cheie_semantica not in grupuri_semantice:
            grupuri_semantice[cheie_semantica] = []

        for v in lista_variante:
            v_copie = dict(v)
            v_copie["_nume_fisier"] = nume_fisier
            grupuri_semantice[cheie_semantica].append(v_copie)

    master_index = {"fisiere": {}, "total_fisiere": 0, "last_updated": ""}
    stari_recuperate = 0

    for cheie_semantica, lista_variante in grupuri_semantice.items():
        variante_valide = [v for v in lista_variante if v["size"] >= 10]
        variante_mici = [v for v in lista_variante if v["size"] < 10]

        for v_mica in variante_mici:
            ids_de_sters.append(v_mica["id"])
            fisiere_mici_eliminate += 1

        if not variante_valide:
            continue

        if len(variante_valide) == 1:
            castigator = variante_valide[0]
        else:
            variante_valide.sort(
                key=lambda x: (
                    1 if x["_nume_fisier"].startswith("brut_XML_") else 0,
                    x["createdTime"]
                ),
                reverse=True
            )
            castigator = variante_valide[0]
            
            for duplicat in variante_valide[1:]:
                ids_de_sters.append(duplicat["id"])

        nume_original = castigator["_nume_fisier"]
        vechea_stare = old_index_map.get(nume_original, {})
        if not vechea_stare:
            nume_alt = nume_original.replace("brut_legislatie_", "brut_XML_") if "brut_legislatie_" in nume_original else nume_original.replace("brut_XML_", "brut_legislatie_")
            vechea_stare = old_index_map.get(nume_alt, {})

        if vechea_stare:
            stari_recuperate += 1

        nume_master = nume_original
        if nume_master.startswith("brut_legislatie_"):
            nume_master = nume_master.replace("brut_legislatie_", "brut_XML_")

        master_index["fisiere"][nume_master] = {
            "id": castigator["id"],
            "folder_id": castigator["folder_id"],
            "createdTime": castigator["createdTime"],
            "size": castigator["size"],
            "downloaded": vechea_stare.get("downloaded", True),
            "Tags_extracted": vechea_stare.get("Tags_extracted", False),
            "processed": vechea_stare.get("processed", False)
        }

        for k, v in vechea_stare.items():
            if k not in master_index["fisiere"][nume_master]:
                master_index["fisiere"][nume_master][k] = v

    master_index["total_fisiere"] = len(master_index["fisiere"])

    print(f"✅ Fișiere XML validate drept MASTER (>=10B): {master_index['total_fisiere']:,}", flush=True)
    print(f"🛡️ Flag-uri de procesare conservate din indexul vechi: {stari_recuperate:,}", flush=True)
    print(f"🗑️ Fișiere goale (<10B) identificate: {fisiere_mici_eliminate:,}", flush=True)
    print(f"🗑️ Total ID-uri trimise la coș: {len(ids_de_sters):,}", flush=True)

    # ==========================================================================
    # 4. SALVARE MASTER INDEX FINAL
    # ==========================================================================
    salvat_cu_succes = salveaza_master_index_xml(
        service, 
        master_index, 
        nume_fisier=NUME_MASTER_INDEX_XML, 
        mesaj="Master Index XML Final Curat (Pre-Trash)"
    )

    if not salvat_cu_succes:
        print("❌ ABORT: Nu s-a putut salva indexul final pe Drive. Se oprește ștergerea.", flush=True)
        sys.exit(1)

    # ==========================================================================
    # 5. TRASH MULTI-THREADED
    # ==========================================================================
    if ids_de_sters:
        executa_trash_multi_threaded(ids_de_sters, max_workers=15)

    # ==========================================================================
    # 6. CURĂȚARE MICRO-INDECȘI
    # ==========================================================================
    curata_micro_indecsi_procesati(service)

    print("\n============================================================", flush=True)
    print("🎉 PROCESUL DE REINDEXARE COMPLETĂ S-A ÎNCHEIAT CU SUCCES!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
