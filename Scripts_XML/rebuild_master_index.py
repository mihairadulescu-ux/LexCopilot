# Filename: Scripts_XML/rebuild_master_index.py
# Scop


import os
import sys
import json
import time
import tarfile
import tempfile
import io
import re
from pathlib import Path

# Line buffering live pentru GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from drive_config import (
    FOLDERE_XML_IDS,
    FOLDER_INDEX_ID,
    get_file_params,
    get_list_params
)


def get_drive_service():
    """Autentificare Google Drive API."""
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
        print(f"❌ [AUTH] Eroare autentificare: {e}", flush=True)
        sys.exit(1)


def cauta_arhive_pe_drives(service):
    """Găsește toate arhivele brut_XML_YYYY.tar.gz de pe toate Shared Drive-urile."""
    arhive_gasite = []
    nume_drives = [d for d in FOLDERE_XML_IDS if d]

    for shared_drive_id in nume_drives:
        try:
            q = "'{}' in parents and name contains 'brut_XML_' and name contains '.tar.gz' and trashed = false".format(shared_drive_id)
            params = get_list_params()
            params["q"] = q
            params["fields"] = "files(id, name, size)"
            res = service.files().list(**params).execute()
            files = res.get("files", [])
            arhive_gasite.extend(files)
        except Exception as e:
            print(f"⚠️ Eroare la căutarea arhivelor în folderul {shared_drive_id}: {e}", flush=True)

    return arhive_gasite


def citeste_toc_arhiva(service, file_id, nume_fisier):
    """Citește Cuprinsul (TOC) dintr-o arhivă .tar.gz de pe Drive fără a descărca XML-urile."""
    pagini_in_arhiva = {}
    m = re.search(r"brut_XML_(\d{4})\.tar\.gz", nume_fisier)
    an = m.group(1) if m else "UNKNOWN"

    try:
        req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        # Descărcare în tampon temporar pentru citirea antetelor tar.gz
        temp_tar = tempfile.NamedTemporaryFile(delete=False)
        temp_tar.write(req.execute())
        temp_tar.close()

        with tarfile.open(temp_tar.name, "r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.endswith(".xml"):
                    # Extragere număr pagină din nume_fisier (ex: brut_XML_1990_pag45.xml -> 45)
                    m_pag = re.search(r"pag(\d+)\.xml$", member.name)
                    if m_pag:
                        numar_pag = m_pag.group(1)
                        pagini_in_arhiva[numar_pag] = {
                            "sursa": "ARHIVA_TAR",
                            "mtime": member.mtime,
                            "dimensiune": member.size
                        }

        os.unlink(temp_tar.name)
    except Exception as e:
        print(f"⚠️ Eroare la citirea TOC-ului pentru {nume_fisier}: {e}", flush=True)

    return an, pagini_in_arhiva


def listeaza_si_citeste_micro_indecsi(service):
    """Găsește și citește toți micro-indecșii index_an_YYYY.json de pe Discul 0."""
    micro_data = {}
    try:
        q = f"'{FOLDER_INDEX_ID}' in parents and name contains 'index_an_' and name contains '.json' and trashed = false"
        params = get_list_params()
        params["q"] = q
        params["fields"] = "files(id, name)"
        res = service.files().list(**params).execute()
        files = res.get("files", [])

        for item in files:
            m = re.search(r"index_an_(\d{4})\.json", item["name"])
            if m:
                an = m.group(1)
                req = service.files().get_media(fileId=item["id"], supportsAllDrives=True)
                content = req.execute().decode('utf-8')
                data_json = json.loads(content)
                micro_data[an] = {
                    "file_id": item["id"],
                    "data": data_json
                }
    except Exception as e:
        print(f"⚠️ Eroare la citirea micro-indecșilor: {e}", flush=True)

    return micro_data


def curata_micro_index(service, file_id, index_data):
    """Golește/Resetează conținutul micro-indexului prelucrat."""
    index_data["pagini_descarcate"] = {}
    index_data["status"] = "PRELUCRAT_IN_MASTER"
    index_data["ultimul_update"] = time.strftime("%Y-%m-%d %H:%M:%S")

    json_bytes = json.dumps(index_data, indent=2, ensure_ascii=False).encode('utf-8')
    media = MediaIoBaseUpload(io.BytesIO(json_bytes), mimetype='application/json')

    params = get_file_params()
    params["fileId"] = file_id
    params["media_body"] = media
    service.files().update(**params).execute()


def reconstruieste_master_index():
    """Audit complet: reconciliere TOC arhive .tar.gz + Micro-indecși."""
    start_time = time.time()
    service = get_drive_service()

    print("============================================================", flush=True)
    print("🚀 RECONSTRUCȚIE TOTALĂ MASTER INDEX (AUDIT TOC + MICRO-INDECȘI)", flush=True)
    print("============================================================", flush=True)

    # 1. Scanare arhive pe Drive
    arhive = cauta_arhive_pe_drives(service)
    print(f"📂 Am găsit {len(arhive)} arhive .tar.gz pe Shared Drives.", flush=True)

    # 2. Citire Micro-indecși
    micro_indecsi = listeaza_si_citeste_micro_indecsi(service)
    print(f"📄 Am găsit {len(micro_indecsi)} micro-indecși pe Discul 0.", flush=True)

    master_index = {
        "generat_la": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_ani_procesati": 0,
        "total_xml_valide": 0,
        "ani": {}
    }

    ani_totali = set()

    # Procesare date din arhive .tar.gz (TOC)
    for arh in arhive:
        nume_fisier = arh["name"]
        file_id = arh["id"]
        print(f"🔍 Scanare TOC arhivă '{nume_fisier}'...", flush=True)

        an, pagini_toc = citeste_toc_arhiva(service, file_id, nume_fisier)
        if an != "UNKNOWN":
            ani_totali.add(an)
            if an not in master_index["ani"]:
                master_index["ani"][an] = {
                    "drive_archive_file_id": file_id,
                    "pagini_ok": {},
                    "ultimul_update": ""
                }

            # Înregistrare pagini din TOC
            for pag_num in pagini_toc:
                master_index["ani"][an]["pagini_ok"][pag_num] = "OK"

    # Procesare și Reconciliere cu Micro-Indecșii
    for an, item in micro_indecsi.items():
        ani_totali.add(an)
        file_id_micro = item["file_id"]
        data_micro = item["data"]
        pagini_micro = data_micro.get("pagini_descarcate", {})

        if an not in master_index["ani"]:
            master_index["ani"][an] = {
                "drive_archive_file_id": data_micro.get("drive_archive_file_id", ""),
                "pagini_ok": {},
                "ultimul_update": data_micro.get("ultimul_update", "")
            }

        # Reconciliere/Păstrare unică a paginilor (Deduplicare)
        pagini_noi_fuzionate = 0
        for pag_num, status in pagini_micro.items():
            if status == "OK":
                if pag_num not in master_index["ani"][an]["pagini_ok"]:
                    pagini_noi_fuzionate += 1
                master_index["ani"][an]["pagini_ok"][pag_num] = "OK"

        if pagini_micro:
            print(f"🔄 Reconciliat micro-index anul {an}: adăugate/validate {pagini_noi_fuzionate} pagini noi.", flush=True)
            # Golire micro-index prelucrat pentru curățare spațiu/redundanță
            curata_micro_index(service, file_id_micro, data_micro)
            print(f"   🧹 Micro-index anul {an} curățat cu succes!", flush=True)

    # Calculare totaluri finale
    total_xml_global = 0
    for an_key in sorted(master_index["ani"].keys()):
        total_pagini_an = len(master_index["ani"][an_key]["pagini_ok"])
        master_index["ani"][an_key]["total_xml_valid"] = total_pagini_an
        total_xml_global += total_pagini_an

    master_index["total_ani_procesati"] = len(master_index["ani"])
    master_index["total_xml_valide"] = total_xml_global

    # Salvare Master Index pe Discul 0
    nume_master = "master_index_XML.json"
    q_master = f"'{FOLDER_INDEX_ID}' in parents and name = '{nume_master}' and trashed = false"
    res_m = service.files().list(q=q_master, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files_m = res_m.get("files", [])
    master_file_id = files_m[0]["id"] if files_m else None

    json_bytes = json.dumps(master_index, indent=2, ensure_ascii=False).encode('utf-8')
    media = MediaIoBaseUpload(io.BytesIO(json_bytes), mimetype='application/json')

    if master_file_id:
        params = get_file_params()
        params["fileId"] = master_file_id
        params["media_body"] = media
        service.files().update(**params).execute()
    else:
        file_metadata = {"name": nume_master, "parents": [FOLDER_INDEX_ID]}
        params = get_file_params()
        params["body"] = file_metadata
        params["media_body"] = media
        res_c = service.files().create(**params).execute()
        master_file_id = res_c.get("id")

    durata = time.time() - start_time
    print("\n" + "=" * 60, flush=True)
    print(f"✨ RECONSTRUCȚIE MASTER INDEX FINALIZATĂ CU SUCCES!", flush=True)
    print(f"📊 Total ani procesați:            {master_index['total_ani_procesati']}", flush=True)
    print(f"🟢 Total pagini XML unice validate: {master_index['total_xml_valide']:,}", flush=True)
    print(f"⏱️  Durată execuție:                {durata / 60:.2f} minute ({durata:.1f}s)", flush=True)
    print(f"💾 File ID Master Index:           {master_file_id}", flush=True)
    print("=" * 60 + "\n", flush=True)


if __name__ == "__main__":
    reconstruieste_master_index()
