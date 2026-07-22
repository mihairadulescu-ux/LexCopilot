import sys
import os
import time
import json
import socket
import re
from pathlib import Path

print("============================================================", flush=True)
print("⚡ SCRIPTUL UPDATE_INCREMENTAL_INDEX.PY A PORNIT!", flush=True)
print("============================================================", flush=True)

socket.setdefaulttimeout(30)

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from drive_config import (
    FOLDER_TEMP_INDEXES_ID,
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

INDEX_FILE_ID = (
    os.getenv("XML_STORAGE_INDEX")
    or os.getenv("INDEX_FILE_ID")
    or getattr(sys.modules.get("drive_config"), "XML_STORAGE_INDEX", None)
    or getattr(sys.modules.get("drive_config"), "INDEX_FILE_ID", None)
    or "1OkPgwX_F6FKwupuhD9kO3rynj4zdel0N"
)

NUME_MASTER_INDEX_XML = "index_xml.json"
MAX_TRASH_PER_BATCH = 500  # Limita de siguranță anti-Rate Limit


def get_drive_service():
    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )

    if not creds_json:
        print("❌ NU S-A GĂSIT SECRETUL GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
        sys.exit(1)

    try:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"❌ Eroare la autentificare: {e}", flush=True)
        sys.exit(1)


def curata_lot_duplicate(service, ids_de_sters):
    if not ids_de_sters:
        print("✨ Nu există fișiere goale sau duplicate de curățat.", flush=True)
        return

    total_de_sters = len(ids_de_sters)
    lot_curent = ids_de_sters[:MAX_TRASH_PER_BATCH]
    
    print(f"\n🧹 Curățare lot de siguranță: {len(lot_curent)} din totalul de {total_de_sters} duplicate...", flush=True)
    
    succes = 0
    for file_id in lot_curent:
        try:
            params = get_file_params(fileId=file_id)
            params["body"] = {"trashed": True}
            service.files().update(**params).execute()
            succes += 1
            if succes % 100 == 0:
                print(f"   ⚡ Curățate: {succes}/{len(lot_curent)}...", flush=True)
        except Exception:
            time.sleep(1)

    print(f"✅ Lot curățat cu succes! ({succes} fișiere trimise la coș)", flush=True)
    if total_de_sters > MAX_TRASH_PER_BATCH:
        print(f"ℹ️ Au rămas {total_de_sters - MAX_TRASH_PER_BATCH} duplicate care vor fi curățate la următoarele rulări periodice.", flush=True)


def main():
    service = get_drive_service()
    print("🔍 Identificare fișiere noi și igienizare...", flush=True)

    # Scanam scurt folderele pentru diferențe și duplicate
    raw_inventory = {}
    pattern_xml = re.compile(r"^brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)

    for folder_id in FOLDERE_XML_IDS:
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            try:
                list_params = get_list_params(
                    q=query,
                    fields="nextPageToken, files(id, name, createdTime, size)",
                    pageToken=page_token,
                    pageSize=1000,
                )
                response = service.files().list(**list_params).execute()
            except Exception:
                break

            files = response.get("files", [])
            if not files:
                break

            for f in files:
                nume = f["name"]
                if nume not in raw_inventory:
                    raw_inventory[nume] = []
                raw_inventory[nume].append({
                    "id": f["id"],
                    "folder_id": folder_id,
                    "createdTime": f.get("createdTime", "1970-01-01T00:00:00.000Z"),
                    "size": int(f.get("size", 0))
                })

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    ids_de_sters = []
    grupuri_semantice = {}

    for nume_fisier, lista_variante in raw_inventory.items():
        match = pattern_xml.match(nume_fisier)
        cheie_semantica = f"{match.group(1)}_pag{match.group(2)}" if match else nume_fisier

        if cheie_semantica not in grupuri_semantice:
            grupuri_semantice[cheie_semantica] = []

        for v in lista_variante:
            v_copie = dict(v)
            v_copie["_nume_fisier"] = nume_fisier
            grupuri_semantice[cheie_semantica].append(v_copie)

    for cheie_semantica, lista_variante in grupuri_semantice.items():
        variante_valide = [v for v in lista_variante if v["size"] >= 10]
        variante_mici = [v for v in lista_variante if v["size"] < 10]

        for v_mica in variante_mici:
            ids_de_sters.append(v_mica["id"])

        if len(variante_valide) > 1:
            variante_valide.sort(
                key=lambda x: (1 if x["_nume_fisier"].startswith("brut_XML_") else 0, x["createdTime"]),
                reverse=True
            )
            for duplicat in variante_valide[1:]:
                ids_de_sters.append(duplicat["id"])

    # Rulam igienizarea doar pe un lot de siguranță
    curata_lot_duplicate(service, ids_de_sters)
    print("\n🎉 PROCES INCREMENTAL & IGIENIZARE FINALIZAT!", flush=True)


if __name__ == "__main__":
    main()
