import os
import sys
import json
import gzip

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from drive_config import FOLDERE_XML_IDS

from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

NOME_INDEX_MASTER = "index_xml.json.gz"


def print_live(msg):
    """Printează și forțează evacuarea instantă a buffer-ului în GitHub Actions."""
    print(msg, flush=True)
    sys.stdout.flush()


def get_drive_service():
    service_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON")
    if not service_json:
        print_live("🛑 [EROARE CRITICĂ] Credențialele Google Drive lipsesc din mediu!")
        sys.exit(1)
    creds_dict = json.loads(service_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds)


def incarc_index_master_gz(cale_local_sau_stream=NOME_INDEX_MASTER):
    if not os.path.exists(cale_local_sau_stream):
        print_live("⚠️ [BUILDER] Nu s-a găsit indexul master local. Se inițializează un index nou.")
        return {}
    try:
        with gzip.open(cale_local_sau_stream, "rb") as f:
            date = json.loads(f.read().decode('utf-8'))
            print_live(f"✅ [BUILDER] Master Index încărcat cu succes ({len(date):,} intrări).")
            return date
    except Exception as e:
        print_live(f"⚠️ [BUILDER] Eroare la citirea indexului master (.gz): {e}")
        return {}


def salveaza_index_master_gz(date_index, cale_salvare=NOME_INDEX_MASTER):
    try:
        with gzip.open(cale_salvare, "wb") as f:
            f.write(json.dumps(date_index, ensure_ascii=False, indent=2).encode('utf-8'))
        dimensiune_mb = os.path.getsize(cale_salvare) / (1024 * 1024)
        print_live(f"💾 [BUILDER] Master Index salvat comprimat ({len(date_index):,} elemente, {dimensiune_mb:.2f} MB).")
        return True
    except Exception as e:
        print_live(f"🛑 [BUILDER] Eroare la salvarea Master Index: {e}")
        return False


def proceseaza_si_curata_microindecsi(service, master_index, batch_size=50):
    print_live("\n⚡ [MICRO-INDEX] Căutare micro-indecși neprocesați pe cele 7 discuri...")
    micro_files = []
    
    for idx, drive_id in enumerate(FOLDERE_XML_IDS, start=1):
        try:
            response = service.files().list(
                q=f"'{drive_id}' in parents and name contains 'micro_index_' and trashed = false",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            gasite = response.get("files", [])
            micro_files.extend(gasite)
            print_live(f"   ├─ Discul {idx}/{len(FOLDERE_XML_IDS)}: {len(gasite)} micro-indecși găsiți")
        except Exception as e:
            print_live(f"⚠️ Eroare scanare micro-indecși pe drive-ul {drive_id}: {e}")

    total_micro = len(micro_files)
    if total_micro == 0:
        print_live("✨ [MICRO-INDEX] Zero micro-indecși de procesat.")
        return master_index

    print_live(f"\n⚡ [MICRO-INDEX] Se procesează {total_micro} micro-indecși în batch-uri de {batch_size}...")

    procesate_count = 0
    for i in range(0, total_micro, batch_size):
        batch = micro_files[i : i + batch_size]
        fisiere_de_sters = []

        for mf in batch:
            procesate_count += 1
            try:
                file_content = service.files().get_media(fileId=mf["id"]).execute()
                data = json.loads(file_content.decode('utf-8'))
                for k, v in data.items():
                    master_index[k] = v
                fisiere_de_sters.append(mf["id"])
            except Exception as e:
                print_live(f"⚠️ Eroare citire micro-index {mf['name']}: {e}")

        for fid in fisiere_de_sters:
            try:
                service.files().delete(fileId=fid, supportsAllDrives=True).execute()
            except Exception as e:
                print_live(f"⚠️ Nu s-a putut șterge micro-indexul {fid}: {e}")

        procent = (procesate_count / total_micro) * 100
        print_live(f"   ⏳ Progres: [{procesate_count}/{total_micro}] ({procent:.1f}%) - Integrat & șters batch {i//batch_size + 1}")

    print_live(f"🎉 [MICRO-INDEX] TOȚI cei {total_micro} micro-indecși au fost integrați și curățați de pe Drive!")
    return master_index


def build_index(mode="INCREMENTAL"):
    service = get_drive_service()

    print_live(f"\n==========================================")
    print_live(f"🚀 [INDEX BUILDER] Pornire în Modul: {mode.upper()}")
    print_live(f"==========================================\n")

    if mode.upper() == "FULL":
        master_index = {}
        fisiere_vazute = {}
        duplicate_sterse = 0
        total_fisiere_scanate = 0
        prag_notificare = 10000

        for index_drive, drive_id in enumerate(FOLDERE_XML_IDS, start=1):
            print_live(f"📂 [SCAN FULL] Shared Drive {index_drive}/{len(FOLDERE_XML_IDS)} (ID: {drive_id[:8]}...)...")
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

                fisiere = response.get("files", [])
                
                for f in fisiere:
                    total_fisiere_scanate += 1
                    fname = f["name"]
                    fid = f["id"]

                    if fname.startswith("brut_XML_") or fname.endswith(".tar.gz"):
                        if fname in fisiere_vazute:
                            try:
                                service.files().delete(fileId=fid, supportsAllDrives=True).execute()
                                duplicate_sterse += 1
                                print_live(f"      🗑️ [DUPLICAT ȘTERS] {fname}")
                            except Exception as e:
                                print_live(f"      ⚠️ Nu s-a putut șterge duplicatul {fname}: {e}")
                        else:
                            fisiere_vazute[fname] = fid
                            is_archive = fname.endswith(".tar.gz")
                            master_index[fname] = {
                                "drive_id": fid,
                                "tip_stocare": "archive" if is_archive else "individual",
                                "arhiva": fname if is_archive else None
                            }

                    # Log live la FIECARE 10.000 de fișiere scanate
                    if total_fisiere_scanate >= prag_notificare:
                        print_live(f"   📊 [PROGRES LIVE] Scanat: {total_fisiere_scanate:,} fișiere | Unice în index: {len(master_index):,}")
                        prag_notificare += 10000

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

        print_live(f"\n✅ [SCAN FULL COMPLET] Total scanat: {total_fisiere_scanate:,} fișiere. Unice: {len(master_index):,}. Duplicate șterse: {duplicate_sterse}.")

        master_index = proceseaza_si_curata_microindecsi(service, master_index)

        print_live("\n🧹 [TRASH] Golire Coșuri de Gunoi pe toate Shared Drive-urile...")
        try:
            service.files().emptyTrash().execute()
            print_live("✨ [TRASH] Coșul de gunoi a fost golit cu succes!")
        except Exception as e:
            print_live(f"⚠️ Nu s-a putut golii Trash-ul automat: {e}")

    else:
        master_index = incarc_index_master_gz()
        master_index = proceseaza_si_curata_microindecsi(service, master_index)

    salveaza_index_master_gz(master_index)
    print_live(f"\n🏁 [INDEX BUILDER] Procesul {mode.upper()} s-a încheiat cu succes!")
    return master_index


if __name__ == "__main__":
    mod_rulare = sys.argv[1] if len(sys.argv) > 1 else "INCREMENTAL"
    build_index(mod_rulare)
