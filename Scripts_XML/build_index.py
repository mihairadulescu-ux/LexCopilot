import os
import sys
import json
import gzip
import time
import re
from pathlib import Path

# Force buffer flush pentru log-uri LIVE în GitHub Actions
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

# ==============================================================================
# CONFIGURARE CONSTANTE & ID-URI
# ==============================================================================
NOME_INDEX_MASTER_LOCAL = "index_xml.json.gz"
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES")
XML_STORAGE_INDEX_ID = os.getenv("XML_STORAGE_INDEX")

if not XML_STORAGE_INDEX_ID:
    print("🛑 EROARE CRITICĂ: Variabila 'XML_STORAGE_INDEX' nu este definită în mediu!", flush=True)
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
            print(f"❌ Eroare la parsarea JSON Service Account: {e}", flush=True)
            sys.exit(1)
            
    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare citire service_account.json local: {e}", flush=True)

    print("❌ Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def Curata_parametri_google(params):
    chei_custom = ["drive_id", "tip_stocare", "arhiva", "cale_interna", "an", "pagina"]
    for k in chei_custom:
        params.pop(k, None)
    return params


def scaneaza_shared_drives_complet(service):
    """
    Scanează fizic de la zero toate cele 7 Shared Drive-uri/Foldere XML.
    Afișează LIVE progresul scanării.
    """
    print(f"\n🔍 [FULL RE-INDEX] Pornire scanare fizică în cele {len(FOLDERE_XML_IDS)} Shared Drive-uri XML...", flush=True)
    master_dict = {}
    pattern = re.compile(r"brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml", re.IGNORECASE)

    total_gasite = 0

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"  📂 Scannare Drive {idx}/{len(FOLDERE_XML_IDS)} (ID: {folder_id})...", flush=True)
        page_token = None
        count_folder = 0

        while True:
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

                # Progres vizual la fiecare 5.000 fișiere
                if count_folder > 0 and count_folder % 5000 == 0:
                    print(f"     ⏳ Am găsit {count_folder:,} fișiere în Drive {idx}...", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Eroare la scanarea folderului {folder_id}: {e}", flush=True)
                break

        print(f"  ✅ Finalizat Drive {idx}/{len(FOLDERE_XML_IDS)}! Găsite: {count_folder:,} fișiere XML.", flush=True)
        total_gasite += count_folder

    print(f"\n🎉 FULL SCAN COMPLET! Total fișiere indexate din Drive: {len(master_dict):,}\n", flush=True)
    return master_dict


def colecteaza_micro_indecsi(service, master_dict):
    """Integrează micro-indecșii neconsolidați peste indexul scanat."""
    if not FOLDER_TEMP_INDEXES_ID:
        return master_dict, []

    print(f"🔍 Verificare micro-indecși în folderul temp (ID: {FOLDER_TEMP_INDEXES_ID})...", flush=True)
    fisiere_temp_de_sters = []
    
    try:
        rezultat = service.files().list(
            q=f"'{FOLDER_TEMP_INDEXES_ID}' in parents and trashed=false and name contains 'temp_index_'",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields="files(id, name)"
        ).execute()

        micro_files = rezultat.get("files", [])
        if micro_files:
            print(f"🧩 Găsiți {len(micro_files)} micro-indecși neconsolidați. Integrare...", flush=True)
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
                except Exception as e:
                    print(f"⚠️ Eroare citire micro-index {mf['name']}: {e}", flush=True)
        else:
            print("ℹ️ Niciun micro-index neconsolidat găsit.", flush=True)

    except Exception as e:
        print(f"⚠️ Eroare scanare micro-indecși: {e}", flush=True)

    return master_dict, fisiere_temp_de_sters


def curata_micro_indecsi_procesati(service, lista_id_uri):
    """Mută în Trash micro-indecșii integrați."""
    if not lista_id_uri:
        return
    print(f"\n🧹 Curățare {len(lista_id_uri)} micro-indecși procesați...", flush=True)
    curatati = 0
    for fid in lista_id_uri:
        try:
            try:
                service.files().delete(fileId=fid, supportsAllDrives=True).execute()
            except Exception:
                service.files().update(
                    fileId=fid,
                    body={'trashed': True},
                    supportsAllDrives=True
                ).execute()
            curatati += 1
        except Exception:
            pass
    print(f"✅ Curățați {curatati}/{len(lista_id_uri)} micro-indecși.", flush=True)


def salveaza_si_urca_master_index_gz(service, master_dict):
    """Comprimă local în .json.gz și face UPDATE pe Google Drive."""
    print(f"\n📦 Comprimare Master Index cu {len(master_dict):,} intrări...", flush=True)
    
    cale_local = Path(NOME_INDEX_MASTER_LOCAL)
    
    with gzip.open(cale_local, "wb") as f:
        json_bytes = json.dumps(master_dict, ensure_ascii=False, indent=2).encode("utf-8")
        f.write(json_bytes)
        
    dimensiune_mb = cale_local.stat().st_size / (1024 * 1024)
    print(f"💾 Arhivă GZIP creată local: {NOME_INDEX_MASTER_LOCAL} ({dimensiune_mb:.2f} MB)", flush=True)

    print(f"⬆️ Actualizare Master Index pe Drive (ID: {XML_STORAGE_INDEX_ID})...", flush=True)
    try:
        media = MediaFileUpload(str(cale_local), mimetype="application/gzip", resumable=True)
        
        params = get_file_params(NOME_INDEX_MASTER_LOCAL)
        params = Curata_parametri_google(params)
        params["fileId"] = XML_STORAGE_INDEX_ID
        params["media_body"] = media
        params["supportsAllDrives"] = True
        params["supportsTeamDrives"] = True

        updated_file = service.files().update(**params).execute()
        print(f"✅ Master Index GZIP actualizat cu succes pe Drive! [ID: {updated_file.get('id')}]", flush=True)
        return True
    except Exception as e:
        print(f"❌ EROARE CRITICĂ la actualizarea Master Index pe Drive: {e}", flush=True)
        return False
    finally:
        if cale_local.exists():
            cale_local.unlink()


def main():
    print("============================================================", flush=True)
    print("🏗️ PORNIRE RE-INDEXARE COMPLETĂ & SCANARE FIZICĂ SHARED DRIVES", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()

    # 1. SCANARE RECURSIVĂ DE LA ZERO PE TOATE CELE 7 SHARED DRIVES
    master_dict = scaneaza_shared_drives_complet(service)

    # 2. INTEGRARE MICRO-INDECȘI
    master_dict, temp_ids_de_sters = colecteaza_micro_indecsi(service, master_dict)

    # 3. COMPRESIE GZIP ȘI UPLOAD
    succes_upload = salveaza_si_urca_master_index_gz(service, master_dict)

    # 4. CURĂȚARE MICRO-INDECȘI
    if succes_upload:
        curata_micro_indecsi_procesati(service, temp_ids_de_sters)

    print("============================================================", flush=True)
    print("🏁 FULL RE-INDEX COMPLET FINALIZAT CU SUCCES!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
