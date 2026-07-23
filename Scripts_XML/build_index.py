import os
import sys
import json
import gzip
import time
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

from drive_config import FOLDERE_XML_IDS, get_file_params

# ==============================================================================
# CONFIGURARE CONSTANTE & ID-URI DIN MEDIU
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


def descarca_master_index_existent(service):
    """Încearcă să descarce și să decompileze Master Index-ul existent de pe Drive."""
    print(f"📥 Descărcare Master Index existent (ID: {XML_STORAGE_INDEX_ID})...", flush=True)
    try:
        request = service.files().get_media(
            fileId=XML_STORAGE_INDEX_ID,
            supportsAllDrives=True
        )
        continut_bytes = request.execute()
        
        # Încercăm să decomprimăm GZIP
        try:
            date_decompresate = gzip.decompress(continut_bytes)
            master_dict = json.loads(date_decompresate.decode("utf-8"))
            print(f"✅ Master Index existent încărcat din GZIP ({len(master_dict):,} intrări).", flush=True)
            return master_dict
        except Exception:
            # Fallback: JSON necomprimat
            try:
                master_dict = json.loads(continut_bytes.decode("utf-8"))
                print(f"⚠️ Master Index era JSON necomprimat. Încărcat ({len(master_dict):,} intrări).", flush=True)
                return master_dict
            except Exception:
                print("⚠️ Fișierul Master Index de pe Drive este invalid/corupt. Se creează un index nou.", flush=True)
                return {}
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca Master Index-ul de pe Drive: {e}", flush=True)
        return {}


def colecteaza_micro_indecsi(service, master_dict):
    """Citește toți micro-indecșii neconsolidați și îi integrează în Master Index."""
    if not FOLDER_TEMP_INDEXES_ID:
        print("ℹ️ 'TEMPORARY_XML_INDEXES' nu este setat. Se sare peste consolidarea micro-indecșilor.", flush=True)
        return master_dict, []

    print(f"🔍 Căutare micro-indecși în folderul temp (ID: {FOLDER_TEMP_INDEXES_ID})...", flush=True)
    fisiere_temp_de_sters = []
    
    try:
        rezultat = service.files().list(
            q=f"'{FOLDER_TEMP_INDEXES_ID}' in parents and trashed=false and name contains 'temp_index_'",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields="files(id, name)"
        ).execute()

        micro_files = rezultat.get("files", [])
        print(f"🧩 Găsiți {len(micro_files)} micro-indecși neconsolidați.", flush=True)

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
                print(f"⚠️ Eroare la procesarea micro-indexului {mf['name']}: {e}", flush=True)

    except Exception as e:
        print(f"⚠️ Eroare la scanarea micro-indecșilor: {e}", flush=True)

    return master_dict, fisiere_temp_de_sters


def curata_micro_indecsi_procesati(service, lista_id_uri):
    """Șterge din Drive micro-indecșii care au fost integrați cu succes în Master Index."""
    if not lista_id_uri:
        return
    print(f"\n🧹 Curățare {len(lista_id_uri)} micro-indecși procesați din Drive...", flush=True)
    stersi_cu_succes = 0
    for fid in lista_id_uri:
        try:
            service.files().delete(
                fileId=fid,
                supportsAllDrives=True
            ).execute()
            stersi_cu_succes += 1
        except Exception as e:
            print(f"⚠️ Nu s-a putut șterge temp_index {fid}: {e}", flush=True)
    print(f"✅ Șterși cu succes {stersi_cu_succes}/{len(lista_id_uri)} micro-indecși.", flush=True)


def salveaza_si_urca_master_index_gz(service, master_dict):
    """Comprimă local în .json.gz și face UPDATE pe Google Drive."""
    print(f"\n📦 Comprimare Master Index cu {len(master_dict):,} intrări...", flush=True)
    
    cale_local = Path(NOME_INDEX_MASTER_LOCAL)
    
    # 1. Scriere fizică comprimată GZIP
    with gzip.open(cale_local, "wb") as f:
        json_bytes = json.dumps(master_dict, ensure_ascii=False, indent=2).encode("utf-8")
        f.write(json_bytes)
        
    dimensiune_kb = cale_local.stat().st_size / 1024
    print(f"💾 Arhivă GZIP creată local: {NOME_INDEX_MASTER_LOCAL} ({dimensiune_kb:.2f} KB)", flush=True)

    # 2. Upload/Update pe Google Drive cu suport pentru Shared Drives
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
    print("🏗️ PORNIRE CONSTRUIRE & COMPACTARE MASTER INDEX XML (.gz)", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()

    # 1. Descărcare Master Index existent
    master_dict = descarca_master_index_existent(service)

    # 2. Integrare micro-indecși
    master_dict, temp_ids_de_sters = colecteaza_micro_indecsi(service, master_dict)

    # 3. Salvare comprimată GZIP și upload
    succes_upload = salveaza_si_urca_master_index_gz(service, master_dict)

    # 4. Curățare micro-indecși integrați DOAR dacă upload-ul pe Drive a reușit
    if succes_upload:
        curata_micro_indecsi_procesati(service, temp_ids_de_sters)
    else:
        print("⚠️ Curățarea micro-indecșilor a fost OPRITĂ deoarece salvarea Master Index-ului pe Drive a eșuat.", flush=True)

    print("============================================================", flush=True)
    print("🏁 PROCES FINALIZAT!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
