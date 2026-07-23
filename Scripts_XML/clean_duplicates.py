import sys
import os
import time
import json
import socket
import re
from pathlib import Path

print("============================================================", flush=True)
print("🧹 SCRIPT DEDICAT PENTRU IGIENIZARE INTENSIVĂ DUPLICATE", flush=True)
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

from drive_config import (
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

BATCH_SIZE = 500      # Câte fișiere trimite la coș per rundă
PAUZA_SEGUNDE = 30    # Pauză între batch-uri pentru a respecta Rate Limits


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


def scaneaza_si_gaseste_duplicate(service):
    print("\n🔍 Scanăm folderele Drive pentru identificare duplicate...", flush=True)
    raw_inventory = {}
    pattern_xml = re.compile(r"^brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)

    for index_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
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
            except Exception as e:
                print(f"⚠️ Eroare citire Drive ({e}). Reîncercăm...", flush=True)
                time.sleep(2)
                service = get_drive_service()
                continue

            files = response.get("files", [])
            if not files:
                break

            for f in files:
                nume = f["name"]
                if nume not in raw_inventory:
                    raw_inventory[nume] = []
                
                raw_inventory[nume].append({
                    "id": f["id"],
                    "createdTime": f.get("createdTime", "1970-01-01T00:00:00.000Z"),
                    "size": int(f.get("size", 0)),
                    "_nume_fisier": nume
                })

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    # Grupare semantică și identificare deșeuri
    grupuri_semantice = {}
    ids_de_sters = []

    for nume_fisier, lista_variante in raw_inventory.items():
        match = pattern_xml.match(nume_fisier)
        cheie_semantica = f"{match.group(1)}_pag{match.group(2)}" if match else nume_fisier

        if cheie_semantica not in grupuri_semantice:
            grupuri_semantice[cheie_semantica] = []

        grupuri_semantice[cheie_semantica].extend(lista_variante)

    for cheie_semantica, lista_variante in grupuri_semantice.items():
        variante_valide = [v for v in lista_variante if v["size"] >= 10]
        variante_mici = [v for v in lista_variante if v["size"] < 10]

        # Fișierele sub 10 bytes se șterg toate
        for v_mica in variante_mici:
            ids_de_sters.append(v_mica["id"])

        # Păstrăm cea mai nouă variantă brut_XML_ (sau brut_legislatie_) și marcăm restul pentru ștergere
        if len(variante_valide) > 1:
            variante_valide.sort(
                key=lambda x: (1 if x["_nume_fisier"].startswith("brut_XML_") else 0, x["createdTime"]),
                reverse=True
            )
            for duplicat in variante_valide[1:]:
                ids_de_sters.append(duplicat["id"])

    return ids_de_sters


def main():
    service = get_drive_service()
    
    # 1. Scanăm o singură dată la început
    ids_de_sters = scaneaza_si_gaseste_duplicate(service)
    total_initial = len(ids_de_sters)

    if not ids_de_sters:
        print("\n✨ FELICITĂRI! Nu a fost găsit niciun duplicat pe Drive! Totul este curat.", flush=True)
        return

    print(f"\n📊 AU FOST IDENTIFICATE {total_initial:,} FIȘIERE DUPLICATE / INVALIDE DE ȘTERS!", flush=True)
    print(f"⚡ Începem ștergerea în loturi de {BATCH_SIZE} cu pauze de {PAUZA_SEGUNDE}s...", flush=True)

    sters_totale = 0

    while ids_de_sters:
        lot_curent = ids_de_sters[:BATCH_SIZE]
        ids_de_sters = ids_de_sters[BATCH_SIZE:]

        print(f"\n🚀 Trimitere la coș LOT ({sters_totale + 1} - {sters_totale + len(lot_curent)} din {total_initial})...", flush=True)
        
        succes_lot = 0
        for file_id in lot_curent:
            for incercare in range(3):
                try:
                    params = get_file_params(fileId=file_id)
                    params["body"] = {"trashed": True}
                    service.files().update(**params).execute()
                    succes_lot += 1
                    break
                except Exception:
                    time.sleep(1)

        sters_totale += succes_lot
        print(f"✅ Executat lot: {succes_lot}/{len(lot_curent)} fișiere mutate la coș. Total șters până acum: {sters_totale:,}/{total_initial:,}", flush=True)

        if ids_de_sters:
            print(f"⏳ Pauză de siguranță {PAUZA_SEGUNDE} secunde înainte de următorul lot...", flush=True)
            time.sleep(PAUZA_SEGUNDE)

    print("\n============================================================", flush=True)
    print(f"🎉 CURĂȚENIE INTENSIVĂ COMPLETĂ! Total fișiere șterse: {sters_totale:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
