import os
import sys
import json
import gzip
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from drive_config import FOLDERE_XML_IDS

# Standard logare live instantanee
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

NOME_INDEX_MASTER = "index_xml.json.gz"


def get_drive_service():
    service_json = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON")
    if not service_json:
        print("🛑 [EROARE CRITICĂ] Credențialele Google Drive lipsesc din mediu!", flush=True)
        sys.exit(1)
    creds_dict = json.loads(service_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds)


def incarc_index_master_gz(cale_local_sau_stream=NOME_INDEX_MASTER):
    """
    Încarcă Master Index-ul existent din arhivă GZIP.
    """
    if not os.path.exists(cale_local_sau_stream):
        print("⚠️ [BUILDER] Nu s-a găsit indexul master local. Se inițializează un index nou.", flush=True)
        return {}
    try:
        with gzip.open(cale_local_sau_stream, "rb") as f:
            date = json.loads(f.read().decode('utf-8'))
            print(f"✅ [BUILDER] Master Index încărcat cu succes ({len(date)} intrări).", flush=True)
            return date
    except Exception as e:
        print(f"⚠️ [BUILDER] Eroare la citirea indexului master (.gz): {e}", flush=True)
        return {}


def salveaza_index_master_gz(date_index, cale_salvare=NOME_INDEX_MASTER):
    """
    Salvează Master Index comprimat GZIP.
    """
    try:
        with gzip.open(cale_salvare, "wb") as f:
            f.write(json.dumps(date_index, ensure_ascii=False, indent=2).encode('utf-8'))
        print(f"💾 [BUILDER] Master Index salvat comprimat ({os.path.getsize(cale_salvare) / (1024*1024):.2f} MB).", flush=True)
        return True
    except Exception as e:
        print(f"🛑 [BUILDER] Eroare la salvarea Master Index: {e}", flush=True)
        return False


def proceseaza_si_curata_microindecsi(service, master_index, batch_size=50):
    """
    Procesează și ȘTERGE FIZIC micro-indecșii în batch-uri controlate.
    """
    print("\n⚡ [MICRO-INDEX] Căutare micro-indecși neprocesați...", flush=True)
    micro_files = []
    
    for drive_id in FOLDERE_XML_IDS:
        try:
            response = service.files().list(
                q=f"'{drive_id}' in parents and name contains 'micro_index_' and trashed = false",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            micro_files.extend(response.get("files", []))
        except Exception as e:
            print(f"⚠️ Eroare scanare micro-indecși pe drive-ul {drive_id}: {e}", flush=True)

    total_micro = len(micro_files)
    if total_micro == 0:
        print("✨ [MICRO-INDEX] Zero micro-indecși de procesat.", flush=True)
        return master_index

    print(f"⚡ [MICRO-INDEX] S-au găsit {total_micro} micro-indecși. Procesare în batch-uri de {batch_size}...", flush=True)

    for i in range(0, total_micro, batch_size):
        batch = micro_files[i : i + batch_size]
        fisiere_de_sters = []

        for mf in batch:
            try:
                file_content = service.files().get_media(fileId=mf["id"]).execute()
                data = json.loads(file_content.decode('utf-8'))
                
                for k, v in data.items():
                    master_index[k] = v
                fisiere_de_sters.append(mf["id"])
            except Exception as e:
                print(f"⚠️ Eroare citire micro-index {mf['name']}: {e}", flush=True)

        for fid in fisiere_de_sters:
            try:
                service.files().delete(fileId=fid, supportsAllDrives=True).execute()
            except Exception as e:
                print(f"⚠️ Nu s-a putut șterge micro-indexul {fid}: {e}", flush=True)

        print(f"✅ [MICRO-INDEX] Batch {i//batch_size + 1}/{(total_micro + batch_size - 1)//batch_size} integrat și curățat.", flush=True)

    print(f"🎉 [MICRO-INDEX] TOȚI cei {total_micro} micro-indecși au fost integrați și șterși!", flush=True)
    return master_index


def scanare_delta_discuri(service, master_index):
    """
    Descoperă fișierele NOI adăugate pe discuri dar care NU figurează încă în Master Index (Delta Integration).
    """
    print("\n🔍 [INCREMENTAL DELTA] Căutare fișiere noi ne-indexate pe discuri...", flush=True)
    fisiere_noi_gasite = 0

    for index_drive, drive_id in enumerate(FOLDERE_XML_IDS, start=1):
        page_token = None
        while True:
            response = service.files().list(
                q=f"'{drive_id}' in parents and trashed = false and (name contains 'brut_XML_' or name contains '.tar.gz')",
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()

            for f in response.get("files", []):
                fname = f["name"]
                fid = f["id"]

                if fname not in master_index:
                    is_archive = fname.endswith(".tar.gz")
                    master_index[fname] = {
                        "drive_id": fid,
                        "tip_stocare": "archive" if is_archive else "individual",
                        "arhiva": fname if is_archive else None
                    }
                    fisiere_noi_gasite += 1

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    print(f"✨ [INCREMENTAL DELTA] S-au descoperit și adăugat {fisiere_noi_gasite} fișiere noi în index.", flush=True)
    return master_index


def build_index(mode="INCREMENTAL"):
    """
    Engine Unic Builder Index:
    - INCREMENTAL: Încarcă Master Index, îmbină/șterge micro-indecșii și adaugă delta de pe discuri.
    - FULL: Rescanează totul de la zero, elimină duplicatele, curăță micro-indecșii și golește Trash-ul.
    """
    service = get_drive_service()

    print(f"\n==========================================", flush=True)
    print(f"🚀 [INDEX BUILDER] Pornire în Modul: {mode}", flush=True)
    print(f"==========================================\n", flush=True)

    if mode.upper() == "FULL":
        master_index = {}
        fisiere_vazute = {}
        duplicate_sterse = 0

        # 1. Rescanare fizică completă & eliminare DUPLICATE
        for index_drive, drive_id in enumerate(FOLDERE_XML_IDS, start=1):
            print(f"📂 [SCAN FULL] Shared Drive {index_drive}/{len(FOLDERE_XML_IDS)} (ID: {drive_id})...", flush=True)
            page_token = None

            while True:
                response = service.files().list(
                    q=f"'{drive_id}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name)",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                for f in response.get("files", []):
                    fname = f["name"]
                    fid = f["id"]

                    if fname.startswith("brut_XML_") or fname.endswith(".tar.gz"):
                        if fname in fisiere_vazute:
                            try:
                                service.files().delete(fileId=fid, supportsAllDrives=True).execute()
                                duplicate_sterse += 1
                                print(f"🗑️ [DUPLICAT ȘTERS] {fname}", flush=True)
                            except Exception as e:
                                print(f"⚠️ Nu s-a putut șterge duplicatul {fname}: {e}", flush=True)
                        else:
                            fisiere_vazute[fname] = fid
                            is_archive = fname.endswith(".tar.gz")
                            master_index[fname] = {
                                "drive_id": fid,
                                "tip_stocare": "archive" if is_archive else "individual",
                                "arhiva": fname if is_archive else None
                            }

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

        print(f"\n✅ [SCAN FULL COMPLET] S-au găsit {len(master_index)} fișiere unice. Sterse {duplicate_sterse} duplicate.", flush=True)

        # 2. Procesare & Ștergere Micro-Indecși
        master_index = proceseaza_si_curata_microindecsi(service, master_index)

        # 3. Golire Coș de Gunoi (Trash)
        print("\n🧹 [TRASH] Golire Coșuri de Gunoi...", flush=True)
        try:
            service.files().emptyTrash().execute()
            print("✨ [TRASH] Coșul de gunoi a fost golit cu succes!", flush=True)
        except Exception as e:
            print(f"⚠️ Nu s-a putut golii Trash-ul automat: {e}", flush=True)

    else:
        # MOD INCREMENTAL
        # 1. Încarcă Master Index existent
        master_index = incarc_index_master_gz()

        # 2. Aplică și șterge micro-indecșii noilor descărcări
        master_index = proceseaza_si_curata_microindecsi(service, master_index)

        # 3. Descoperă fișiere noi adăugate direct pe discuri (Delta Integration)
        master_index = scanare_delta_discuri(service, master_index)

    # Salvare starea finală comprimată GZIP
    salveaza_index_master_gz(master_index)
    print(f"\n🏁 [INDEX BUILDER] Procesul {mode} s-a încheiat cu succes!", flush=True)
    return master_index


if __name__ == "__main__":
    mod_rulare = sys.argv[1] if len(sys.argv) > 1 else "INCREMENTAL"
    build_index(mod_rulare)
