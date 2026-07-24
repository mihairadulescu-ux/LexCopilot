import os
import sys
import json
import time
import gzip
import io
from pathlib import Path

# Stream direct live fără buffer
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from drive_config import FOLDER_INDEX_ID, get_file_params, get_list_params


def get_drive_service():
    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )
    if not creds_json:
        print("❌ [AUTH] Lipsă secret GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
        sys.exit(1)

    try:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        print(f"❌ [AUTH] Eroare Google Drive: {e}", flush=True)
        sys.exit(1)


def descarca_json_gz_din_drive(service, file_id):
    """Descarcă și decomprimă un fișier .gz direct din memorie."""
    try:
        req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        continut_comprimat = req.execute()
        with gzip.GzipFile(fileobj=io.BytesIO(continut_comprimat), mode='rb') as gz:
            text_json = gz.read().decode('utf-8')
            return json.loads(text_json)
    except Exception as e:
        print(f"⚠️ Eroare la citirea MasterIndex.json.gz (ID {file_id}): {e}", flush=True)
        return None


def descarca_json_text_din_drive(service, file_id):
    """Descarcă un fișier JSON text necomprimat de pe Drive."""
    try:
        req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        text = req.execute().decode('utf-8')
        if not text.strip():
            return {}
        return json.loads(text)
    except Exception:
        return {}


def goleleste_micro_index_pe_drive(service, file_id, file_name):
    """
    Încearcă să golească micro-indexul pe Drive. 
    Dacă întâmpină erori de scriere/rețea, doar le raportează și continuă fără să crape procesul.
    """
    try:
        json_gol = "{}"
        media = MediaIoBaseUpload(
            io.BytesIO(json_gol.encode('utf-8')),
            mimetype='application/json'
        )
        params = get_file_params()
        params["fileId"] = file_id
        params["media_body"] = media
        service.files().update(**params).execute()
        print(f"   🧹 Micro-index-ul '{file_name}' a fost golit pe Drive.", flush=True)
    except Exception as e:
        print(f"⚠️ Ignorat: Nu s-a putut goli micro-indexul '{file_name}' din motive de rețea/blocaj: {e}", flush=True)


def unifica_in_master_index(reset_complet=False):
    service = get_drive_service()

    print("============================================================", flush=True)
    print(f"🔄 UNIFICARE MASTER INDEX COMPRIMAT (.gz) | Discul 0: {FOLDER_INDEX_ID}", flush=True)
    print("============================================================", flush=True)

    # 1. Căutăm MasterIndex.json.gz pe Discul 0
    q_master = f"'{FOLDER_INDEX_ID}' in parents and name = 'MasterIndex.json.gz' and trashed=false"
    params_master = get_list_params()
    params_master["q"] = q_master
    params_master["fields"] = "files(id, name)"
    
    res_master = service.files().list(**params_master).execute()
    files_master = res_master.get("files", [])

    master_file_id = None
    master_data = {
        "ultimul_sync": "",
        "total_ani_procesati": 0,
        "total_xml_valide": 0,
        "arhive": {},
        "fisiere": {}  # Folosește dicționar pentru a gestiona natural dublurile prin suprascriere (deduplicare)
    }

    if files_master and not reset_complet:
        master_file_id = files_master[0]["id"]
        print(f"📥 MasterIndex.json.gz existent găsit (ID: {master_file_id}). Decomprimare și încărcare...", flush=True)
        date_incarcate = descarca_json_gz_din_drive(service, master_file_id)
        if date_incarcate:
            master_data.update(date_incarcate)
    elif files_master and reset_complet:
        master_file_id = files_master[0]["id"]
        print("⚠️ [RESET] Resetare completă solicitată! MasterIndex va fi golit și refăcut de la zero...", flush=True)

    # 2. Căutăm micro-indecșii unici pe an: index_an_*.json
    q_micro = f"'{FOLDER_INDEX_ID}' in parents and name contains 'index_an_' and name contains '.json' and trashed=false"
    params_micro = get_list_params()
    params_micro["q"] = q_micro
    params_micro["fields"] = "files(id, name)"
    
    res_micro = service.files().list(**params_micro).execute()
    micro_files = res_micro.get("files", [])

    print(f"🔍 Identificați {len(micro_files)} micro-indecși pe Discul 0...", flush=True)

    micro_procesati = 0

    for f_micro in micro_files:
        micro_id = f_micro["id"]
        micro_name = f_micro["name"]
        
        micro_content = descarca_json_text_din_drive(service, micro_id)
        
        # Dacă micro-indexul este gol `{}`, nu avem ce procesa
        if not micro_content or len(micro_content) == 0:
            continue

        an = micro_content.get("an")
        archive_file_id = micro_content.get("drive_archive_file_id")
        pagini = micro_content.get("pagini_descarcate", {})

        if not an or not archive_file_id:
            continue

        print(f"➕ Contopire micro-index pentru Anul {an} în MasterIndex...", flush=True)

        # Actualizăm metadatele despre arhivă (suprascriere curată)
        master_data["arhive"][str(an)] = {
            "archive_file_id": archive_file_id,
            "status": micro_content.get("status", "IN_PROGRES"),
            "ultimul_update": micro_content.get("ultimul_update", ""),
            "total_xml_valid": micro_content.get("total_xml_valid", 0)
        }

        # Generăm căile deterministe pentru pagini. 
        # Dicționarul previne duplicatele prin suprascrierea curată a aceleiași chei (nume_xml).
        for nr_pagina, stadiu in pagini.items():
            if stadiu == "OK":
                nume_xml = f"brut_XML_{an}_pag{nr_pagina}.xml"
                master_data["fisiere"][nume_xml] = {
                    "an": int(an),
                    "pagina": int(nr_pagina),
                    "archive_file_id": archive_file_id,
                    "cale_in_arhiva": nume_xml
                }

        # 3. Încercăm golirea micro-indexului pe Drive. Dacă eșuează, trece mai departe fără erori.
        goleleste_micro_index_pe_drive(service, micro_id, micro_name)
        micro_procesati += 1

    # Recalculare totaluri unificate
    master_data["ultimul_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
    master_data["total_ani_procesati"] = len(master_data["arhive"])
    master_data["total_xml_valide"] = len(master_data["fisiere"])

    # 4. Comprimare locală în `.gz` și încărcare pe Drive
    cale_gz_temp = RADACINA_PROIECT / "MasterIndex.json.gz"
    
    json_bytes = json.dumps(master_data, indent=2, ensure_ascii=False).encode('utf-8')
    with gzip.open(cale_gz_temp, 'wb') as gz_out:
        gz_out.write(json_bytes)

    marime_mb = cale_gz_temp.stat().st_size / (1024 * 1024)
    media = MediaFileUpload(str(cale_gz_temp), mimetype="application/gzip", resumable=True)

    if master_file_id:
        print(f"\n🔄 Actualizare 'MasterIndex.json.gz' pe Discul 0 ({marime_mb:.2f} MB)...", flush=True)
        params = get_file_params()
        params["fileId"] = master_file_id
        params["media_body"] = media
        service.files().update(**params).execute()
    else:
        print(f"\n☁️ Creare 'MasterIndex.json.gz' nou pe Discul 0 ({marime_mb:.2f} MB)...", flush=True)
        file_metadata = {
            "name": "MasterIndex.json.gz",
            "parents": [FOLDER_INDEX_ID]
        }
        params = get_file_params()
        params["body"] = file_metadata
        params["media_body"] = media
        res_create = service.files().create(**params).execute()
        master_file_id = res_create.get("id")

    cale_gz_temp.unlink(missing_ok=True)

    print("\n============================================================", flush=True)
    print(f"✅ UNIFICARE MASTER INDEX FINALIZATĂ CU SUCCES!", flush=True)
    print(f"📊 Micro-indecși procesați: {micro_procesati}", flush=True)
    print(f"📊 Total ani unificați: {master_data['total_ani_procesati']} | Total fișiere XML unice mapate: {master_data['total_xml_valide']:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    reset_arg = len(sys.argv) >= 2 and sys.argv[1].lower() == "reset"
    unifica_in_master_index(reset_complet=reset_arg)
