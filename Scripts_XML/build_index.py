import os
import sys
import json
import gzip
import time
import re
from pathlib import Path
from collections import defaultdict

# Live logging unbuffered
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ==============================================================================
# CONFIGURARE CĂI
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from drive_config import FOLDERE_XML_IDS

DIMENSIUNE_BATCH = 100
PAUZA_SECUENTI_SEC = 2.5
CHECKPOINT_SALVARE = 1000  # Salvează indexul incremental la fiecare 1000 elemente


def get_drive_service():
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
            print(f"❌ [AUTH] Eroare parsare Service Account JSON: {e}", flush=True)
            sys.exit(1)
            
    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ [AUTH] Eroare citire service_account.json local: {e}", flush=True)

    print("❌ [AUTH] Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def salveaza_checkpoint_index(cale_file, index_dict):
    """Scrie incremental starea curentă a indexului pe disc."""
    try:
        with gzip.open(cale_file, "wb") as f_gz:
            f_gz.write(json.dumps(index_dict, ensure_ascii=False, indent=2).encode('utf-8'))
        print(f"   💾 [CHECKPOINT] Index salvat pe disc ({len(index_dict)} ani înregistrați).", flush=True)
    except Exception as e:
        print(f"   ⚠️ Eroare salvare checkpoint: {e}", flush=True)


def build_master_index():
    print("============================================================", flush=True)
    print("🚀 MASTER INDEX XML + ELIMINARE DUPLICATE CU SALVARE INCREMENTALĂ", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()
    cale_index_local = RADACINA_PROIECT / "index_xml.json.gz"

    # ÎNCĂRCARE INDEX EXISTENT PENTRU APPEND / UPDATE
    index_dict = {}
    if cale_index_local.exists():
        try:
            with gzip.open(cale_index_local, "rb") as f_gz:
                index_dict = json.loads(f_gz.read().decode('utf-8'))
            print(f"📦 Index existent încărcat ({len(index_dict)} ani existenți). Se va face append.", flush=True)
        except Exception as e:
            print(f"⚠️ Nu s-a putut citi indexul vechi (se re-creează de la zero): {e}", flush=True)

    harta_fisiere = defaultdict(list)
    total_fisiere_brute = 0
    pattern_xml = re.compile(r"brut_XML_(\d+)_pag(\d+)\.xml", re.IGNORECASE)

    # --------------------------------------------------------------------------
    # PAS 1: CARTOGRAFIERE SHARED DRIVE-URI
    # --------------------------------------------------------------------------
    print("\n🔍 [PAS 1] Cartografiere fișiere XML din toate cele 7 Shared Drive-uri...", flush=True)

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        page_token = None
        count_drive = 0

        while True:
            try:
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false and name contains '.xml'",
                    spaces='drive',
                    fields="nextPageToken, files(id, name, createdTime)",
                    pageToken=page_token,
                    pageSize=1000,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = response.get('files', [])
                for f in files:
                    harta_fisiere[f['name']].append({
                        'id': f['id'],
                        'drive_idx': idx,
                        'createdTime': f.get('createdTime', '')
                    })
                    total_fisiere_brute += 1
                    count_drive += 1

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Eroare la scanare Drive {idx}: {e}", flush=True)
                break

        print(f"   📂 Drive [{idx}/{len(FOLDERE_XML_IDS)}]: Găsite {count_drive:,} fișiere XML.", flush=True)

    print(f"\n✅ Cartografiere gata: {total_fisiere_brute:,} fișiere brute ({len(harta_fisiere):,} denumiri unice).", flush=True)

    # --------------------------------------------------------------------------
    # PAS 2: DEDUPLICARE & SALVARE INCREMENTALĂ ÎN INDEX
    # --------------------------------------------------------------------------
    print("\n🗑️ [PAS 2] Deduplicare pe Drive & actualizare incrementală a indexului...", flush=True)
    
    total_duplicate_sterse = 0
    actiuni_batch = 0
    numar_batch = 1
    fisiere_procesate = 0

    for nume_fisier, lista_copii in harta_fisiere.items():
        fisiere_procesate += 1

        # 1. Ștergere duplicate dacă există mai multe copii
        if len(lista_copii) > 1:
            lista_copii.sort(key=lambda x: x['createdTime'], reverse=True)
            copie_valida = lista_copii[0]

            for dup in lista_copii[1:]:
                try:
                    service.files().delete(
                        fileId=dup['id'],
                        supportsAllDrives=True,
                        supportsTeamDrives=True
                    ).execute()

                    total_duplicate_sterse += 1
                    actiuni_batch += 1
                    print(f"   🗑️ [{total_duplicate_sterse:,}] Șters duplicat '{nume_fisier}' [ID: {dup['id']}]", flush=True)

                    if actiuni_batch >= DIMENSIUNE_BATCH:
                        print(f"\n☕ [BATCH {numar_batch} DUPLICATE COMPLET] Pauză {PAUZA_SECUENTI_SEC}s...", flush=True)
                        salveaza_checkpoint_index(cale_index_local, index_dict)
                        time.sleep(PAUZA_SECUENTI_SEC)
                        numar_batch += 1
                        actiuni_batch = 0

                except Exception as e_del:
                    print(f"   ⚠️ Eroare ștergere duplicat {dup['id']}: {e_del}", flush=True)
        else:
            copie_valida = lista_copii[0]

        # 2. Adăugare/Append în structura de index
        m = pattern_xml.match(nume_fisier)
        if m:
            an = str(m.group(1))
            pagina = str(m.group(2))
            
            if an not in index_dict:
                index_dict[an] = {}

            index_dict[an][pagina] = {
                "id": copie_valida['id'],
                "drive_idx": copie_valida['drive_idx'],
                "nume": nume_fisier
            }

        # 3. Checkpoint automat din N în N fișiere
        if fisiere_procesate % CHECKPOINT_SALVARE == 0:
            salveaza_checkpoint_index(cale_index_local, index_dict)

    # SALVARE FINALĂ
    salveaza_checkpoint_index(cale_index_local, index_dict)

    print("\n============================================================", flush=True)
    print(f"🏁 PROCES FINALIZAT CU SUCCES!", flush=True)
    print(f"📄 Fișier index: {cale_index_local.name}", flush=True)
    print(f"📊 Ani indexați: {len(index_dict)} | Duplicate eliminate: {total_duplicate_sterse:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    build_master_index()import os
import sys
import json
import gzip
import time
import re
from pathlib import Path

# Logare live instantanee (unbuffered output)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

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

from drive_config import FOLDERE_XML_IDS, get_file_params

NOME_INDEX_MASTER_LOCAL = "index_xml.json.gz"
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES")
XML_STORAGE_INDEX_ID = os.getenv("XML_STORAGE_INDEX")

if not XML_STORAGE_INDEX_ID:
    print("🛑 [EROARE CRITICĂ] Variabila 'XML_STORAGE_INDEX' nu este definită în mediu!", flush=True)
    sys.exit(1)


def get_drive_service():
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
            print(f"❌ [AUTH] Eroare la parsarea JSON Service Account: {e}", flush=True)
            sys.exit(1)
            
    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ [AUTH] Eroare citire service_account.json local: {e}", flush=True)

    print("❌ [AUTH] Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def Curata_parametri_google(params):
    chei_custom = ["drive_id", "tip_stocare", "arhiva", "cale_interna", "an", "pagina"]
    for k in chei_custom:
        params.pop(k, None)
    return params


def scaneaza_shared_drives_complet(service):
    """Scanează fizic de la zero toate cele 7 Shared Drive-uri XML."""
    t_start = time.time()
    print(f"\n🔍 [FULL SCAN] Pornire scanare fizică în cele {len(FOLDERE_XML_IDS)} Shared Drive-uri XML...", flush=True)
    master_dict = {}
    pattern = re.compile(r"brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml", re.IGNORECASE)

    total_fisiere_scanate = 0

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n📂 [{idx}/{len(FOLDERE_XML_IDS)}] Scanare Shared Drive ID: {folder_id}", flush=True)
        page_token = None
        count_folder = 0
        pasi_pagina = 0

        while True:
            pasi_pagina += 1
            try:
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false and name contains 'brut_'",
                    spaces='drive',
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=1000,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = response.get('files', [])
                for f in files:
                    nume = f['name']
                    match = pattern.match(nume)
                    if match:
                        an = int(match.group(1))
                        pagina = int(match.group(2))
                        nume_standard = f"brut_XML_{an}_pag{pagina}.xml"
                        
                        master_dict[nume_standard] = {
                            "an": an,
                            "pagina": pagina,
                            "tip_stocare": "individual",
                            "arhiva": None,
                            "cale_interna": None,
                            "drive_id": f['id']
                        }
                        count_folder += 1

                print(f"   ⏳ [Drive {idx}/{len(FOLDERE_XML_IDS)}] Pagina {pasi_pagina} interogată | +{len(files)} fișiere găsite (Total folder: {count_folder:,})", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except Exception as e:
                print(f"   ⚠️ [Eroare Folder {folder_id}]: {e}", flush=True)
                break

        total_fisiere_scanate += count_folder
        print(f"   ✅ [Drive {idx}/{len(FOLDERE_XML_IDS)}] Finalizat! Total fișiere unice colectate: {count_folder:,}", flush=True)

    durata = time.time() - t_start
    print(f"\n🎉 [FULL SCAN COMPLET] Scanat în {durata:.2f}s | Total fișiere unice indexate: {len(master_dict):,}\n", flush=True)
    return master_dict


def colecteaza_toti_micro_indecsii(service, master_dict):
    """Caută și citește ABSOLUT TOȚI micro-indecșii neconsolidați."""
    if not FOLDER_TEMP_INDEXES_ID:
        print("ℹ️ [MICRO-INDEX] TEMPORARY_XML_INDEXES nu este setat.", flush=True)
        return master_dict, []

    print(f"🔍 [MICRO-INDEX] Căutare paginată a TUTUROR micro-indecșilor în folderul temp (ID: {FOLDER_TEMP_INDEXES_ID})...", flush=True)
    fisiere_temp_de_sters = []
    total_micro_gasite = 0
    page_token = None
    pagina_nr = 0

    while True:
        pagina_nr += 1
        try:
            rezultat = service.files().list(
                q=f"'{FOLDER_TEMP_INDEXES_ID}' in parents and trashed=false and name contains 'temp_index_'",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=1000,
                pageToken=page_token,
                fields="nextPageToken, files(id, name)"
            ).execute()

            micro_files = rezultat.get("files", [])
            if micro_files:
                print(f"   🧩 Pagina {pagina_nr} micro-indecși: Găsite {len(micro_files)} fișiere. Ingerare...", flush=True)
                for mf in micro_files:
                    try:
                        req = service.files().get_media(
                            fileId=mf["id"],
                            supportsAllDrives=True
                        )
                        continut = req.execute()
                        date_micro = json.loads(continut.decode("utf-8"))
                        updates = date_micro.get("flag_updates", {})
                        
                        master_dict.update(updates)
                        fisiere_temp_de_sters.append(mf["id"])
                        total_micro_gasite += 1
                    except Exception as e:
                        print(f"   ⚠️ Eroare la citirea micro-indexului {mf['name']}: {e}", flush=True)
            
            page_token = rezultat.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            print(f"⚠️ [MICRO-INDEX] Eroare la interogarea listei: {e}", flush=True)
            break

    print(f"✅ [MICRO-INDEX COMPLET] Au fost ingerați cu succes TOȚI cei {total_micro_gasite} micro-indecși!\n", flush=True)
    return master_dict, fisiere_temp_de_sters


def trimite_micro_indecsii_la_trash(service, lista_id_uri):
    """Mută la Trash toți micro-indecșii procesați în batch-uri de 100 cu pauze."""
    total = len(lista_id_uri)
    if total == 0:
        print("ℹ️ [TRASH] Nu există micro-indecși de curățat.", flush=True)
        return

    print(f"🧹 [TRASH] Se mută la Trash TOȚI cei {total} micro-indecși procesați (în batch-uri de 100)...", flush=True)
    curatati = 0
    actiuni_batch = 0
    numar_batch = 1

    for idx, fid in enumerate(lista_id_uri, start=1):
        try:
            service.files().update(
                fileId=fid,
                body={'trashed': True},
                supportsAllDrives=True,
                supportsTeamDrives=True
            ).execute()
            curatati += 1
            actiuni_batch += 1

            if actiuni_batch >= 100:
                print(f"   ☕ [BATCH TRASH {numar_batch}] Mutați 100 micro-indecși în Trash ({curatati}/{total}). Pauză 2.5s...", flush=True)
                time.sleep(2.5)
                numar_batch += 1
                actiuni_batch = 0

        except Exception:
            pass

    print(f"✅ [TRASH COMPLET] Curățare finalizată! {curatati}/{total} micro-indecși mutați în Trash.\n", flush=True)


def salveaza_si_urca_master_index_gz(service, master_dict):
    """Comprimă local în .json.gz și forțează mimeType=application/gzip pe Google Drive."""
    print(f"📦 [COMPRESIE] Generare Master Index GZIP ({len(master_dict):,} intrări totale)...", flush=True)
    
    cale_local = Path(NOME_INDEX_MASTER_LOCAL)
    t_start = time.time()
    
    with gzip.open(cale_local, "wb") as f:
        json_bytes = json.dumps(master_dict, ensure_ascii=False, indent=2).encode("utf-8")
        f.write(json_bytes)
        
    dimensiune_mb = cale_local.stat().st_size / (1024 * 1024)
    print(f"💾 Arhivă locală GZIP creată în {time.time() - t_start:.2f}s | Dimensiune: {dimensiune_mb:.2f} MB", flush=True)

    print(f"⬆️ [UPLOAD] Actualizare Master Index GZIP pe Drive (ID: {XML_STORAGE_INDEX_ID})...", flush=True)
    try:
        media = MediaFileUpload(
            str(cale_local), 
            mimetype="application/gzip", 
            resumable=True
        )
        
        file_metadata = {
            "name": "index_xml.json.gz",
            "mimeType": "application/gzip"
        }

        updated_file = service.files().update(
            fileId=XML_STORAGE_INDEX_ID,
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True,
            supportsTeamDrives=True
        ).execute()

        print(f"✅ [UPLOAD REUȘIT] Master Index salvat ca GZIP real pe Drive! [ID: {updated_file.get('id')}]", flush=True)
        return True
    except Exception as e:
        print(f"❌ [UPLOAD EȘUAT] Eroare la actualizarea Master Index pe Drive: {e}", flush=True)
        return False
    finally:
        if cale_local.exists():
            cale_local.unlink()


def main():
    t_global = time.time()
    print("============================================================", flush=True)
    print("🏗️ ENGINE INDEXARE: SCANARE DRIVES + INGERARE MICRO-INDECȘI + TRASH CLEANUP", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()

    # 1. SCANARE RECURSIVĂ DE LA ZERO PE TOATE CELE 7 SHARED DRIVES
    master_dict = scaneaza_shared_drives_complet(service)

    # 2. INGERARE PAGINATĂ A TUTUROR MICRO-INDECȘILOR EXISTENȚI
    master_dict, temp_ids_de_sters = colecteaza_toti_micro_indecsii(service, master_dict)

    # 3. COMPRESIE GZIP ȘI UPLOAD PE DRIVE A NOULUI MASTER INDEX (.gz)
    succes_upload = salveaza_si_urca_master_index_gz(service, master_dict)

    # 4. MUTAREA LA TRASH A TUTUROR MICRO-INDECȘILOR PROCESAȚI
    if succes_upload:
        trimite_micro_indecsii_la_trash(service, temp_ids_de_sters)

    durata_totala = time.time() - t_global
    print("============================================================", flush=True)
    print(f"🏁 PROCES DE RE-INDEXARE ȘI CURĂȚARE FINALIZAT ÎN {durata_totala:.2f} SECUNDE!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
