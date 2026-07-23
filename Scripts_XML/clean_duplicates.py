import sys
import os
import time
import json
import socket
import re
from pathlib import Path

# Printăm instant un header ca să știm că a pornit
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
PAUZA_SEGUNDE = 15    # Pauză redusă la 15s pentru viteză sporită


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
    print("🔍 Scanăm folderele Drive pentru identificare duplicate...", flush=True)
    raw_inventory = {}
    pattern_xml = re.compile(r"^brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)

    for index_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"   └─ Folder [{index_folder}/{len(FOLDERE_XML_IDS)}] ID: {folder_id}...", flush=True)
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

        for v_mica in variante_mici:
            ids_de_sters.append(v_mica["id"])

        if len(variante_valide) > 1:
            variante_valide.sort(
                key=lambda x: (1 if x["_nume_fisier"].startswith("brut_XML_") else 0, x["createdTime"]),
                reverse=True
            )
            for duplicat in variante_valide[1:]:
                ids_de_sters.append(duplicat["id"])

    return ids_de_sters


def genereaza_bara_progres(curent, total, lungime=25):
    procent = (curent / total) * 100 if total > 0 else 100
    plini = int(lungime * curent // total) if total > 0 else lungime
    bara = "█" * plini + "░" * (lungime - plini)
    return f"[{bara}] {procent:.1f}%"


def formateaza_timp(secunde):
    m, s = divmod(int(secunde), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def main():
    service = get_drive_service()
    
    ids_de_sters = scaneaza_si_gaseste_duplicate(service)
    total_initial = len(ids_de_sters)

    if not ids_de_sters:
        print("\n✨ FELICITĂRI! Nu a fost găsit niciun duplicat pe Drive! Totul este curat.", flush=True)
        return

    print(f"\n📊 AU FOST IDENTIFICATE {total_initial:,} FIȘIERE DUPLICATE / INVALIDE DE ȘTERS!", flush=True)
    print(f"⚡ Începem ștergerea în loturi de {BATCH_SIZE} cu pauze de {PAUZA_SEGUNDE}s...\n", flush=True)

    sters_totale = 0
    timp_start_stergere = time.time()

    while ids_de_sters:
        lot_curent = ids_de_sters[:BATCH_SIZE]
        ids_de_sters = ids_de_sters[BATCH_SIZE:]

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
                    time.sleep(0.5)

        sters_totale += succes_lot
        durata_cumulata = time.time() - timp_start_stergere
        viteză_medie = sters_totale / durata_cumulata if durata_cumulata > 0 else 0
        
        fisiere_ramase = total_initial - sters_totale
        eta_secunde = (fisiere_ramase / viteză_medie) if viteză_medie > 0 else 0

        bara = genereaza_bara_progres(sters_totale, total_initial)
        
        # Printăm pe rânduri separate ca să forțăm flush-ul din consola GitHub
        print(f"🚀 LOT FINALIZAT: +{succes_lot} fișiere trimise la coș", flush=True)
        print(f"   ├─ Progres: {bara} ({sters_totale:,}/{total_initial:,})", flush=True)
        print(f"   ├─ Viteză: {viteză_medie:.1f} fișiere/secundă", flush=True)
        print(f"   └─ Timp rămas estimat (ETA): {formateaza_timp(eta_secunde)}", flush=True)
        print("------------------------------------------------------------", flush=True)

        if ids_de_sters:
            time.sleep(PAUZA_SEGUNDE)

    print("\n============================================================", flush=True)
    print(f"🎉 CURĂȚENIE INTENSIVĂ COMPLETĂ! Total fișiere șterse: {sters_totale:,} în {formateaza_timp(time.time() - timp_start_stergere)}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
