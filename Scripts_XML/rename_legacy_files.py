import sys
import os
import time
import json
import socket
import re
from pathlib import Path

print("============================================================", flush=True)
print("🏷️ SCRIPT DEDICAT PENTRU REDENUMIREA FIȘIERELOR LEGACY (brut_legislatie_ -> brut_XML_)", flush=True)
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

BATCH_SIZE = 500      # Număr de redenumiri per lot
PAUZA_SEGUNDE = 5     # Redenumirea e foarte ușoară pentru Drive, ajung 5 secunde pauză


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


def scaneaza_fisiere_legacy(service):
    print("🔍 Identificare fișiere cu denumire veche (brut_legislatie_)...", flush=True)
    fisiere_de_redenumit = []
    pattern_vechi = re.compile(r"^brut_legislatie_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)

    for index_folder, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"   └─ Scanăm Folder [{index_folder}/{len(FOLDERE_XML_IDS)}] ID: {folder_id}...", flush=True)
        page_token = None
        # Căutăm direct fișierele care încep cu brut_legislatie
        query = f"'{folder_id}' in parents and name contains 'brut_legislatie_' and trashed = false"

        while True:
            try:
                list_params = get_list_params(
                    q=query,
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=1000,
                )
                response = service.files().list(**list_params).execute()
            except Exception as e:
                print(f"⚠️ Eroare la scanare Drive ({e}). Reîncercăm...", flush=True)
                time.sleep(2)
                service = get_drive_service()
                continue

            files = response.get("files", [])
            if not files:
                break

            for f in files:
                nume_vechi = f["name"]
                match = pattern_vechi.match(nume_vechi)
                if match:
                    nume_nou = f"brut_XML_{match.group(1)}_pag{match.group(2)}.xml"
                    fisiere_de_redenumit.append({
                        "id": f["id"],
                        "nume_vechi": nume_vechi,
                        "nume_nou": nume_nou
                    })

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return fisiere_de_redenumit


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
    
    fisiere = scaneaza_fisiere_legacy(service)
    total_initial = len(fisiere)

    if not fisiere:
        print("\n✨ FELICITĂRI! Toate fișierele de pe Drive au deja denumirea standard brut_XML_!", flush=True)
        return

    print(f"\n📊 AU FOST IDENTIFICATE {total_initial:,} FIȘIERE LEGACY PENTRU REDENUMIRE!", flush=True)
    print(f"⚡ Începem redenumirea în loturi de {BATCH_SIZE}...\n", flush=True)

    redenumite_totale = 0
    timp_start = time.time()

    while fisiere:
        lot_curent = fisiere[:BATCH_SIZE]
        fisiere = fisiere[BATCH_SIZE:]

        succes_lot = 0

        for item in lot_curent:
            for incercare in range(3):
                try:
                    params = get_file_params(fileId=item["id"])
                    params["body"] = {"name": item["nume_nou"]}
                    service.files().update(**params).execute()
                    succes_lot += 1
                    break
                except Exception:
                    time.sleep(0.5)

        redenumite_totale += succes_lot
        durata_cumulata = time.time() - timp_start
        viteză_medie = redenumite_totale / durata_cumulata if durata_cumulata > 0 else 0
        
        fisiere_ramase = total_initial - redenumite_totale
        eta_secunde = (fisiere_ramase / viteză_medie) if viteză_medie > 0 else 0

        bara = genereaza_bara_progres(redenumite_totale, total_initial)
        
        print(f"🏷️ LOT FINALIZAT: +{succes_lot} fișiere redenumite în 'brut_XML_...'", flush=True)
        print(f"   ├─ Progres: {bara} ({redenumite_totale:,}/{total_initial:,})", flush=True)
        print(f"   ├─ Viteză: {viteză_medie:.1f} redenumiri/secundă", flush=True)
        print(f"   └─ Timp rămas estimat (ETA): {formateaza_timp(eta_secunde)}", flush=True)
        print("------------------------------------------------------------", flush=True)

        if fisiere:
            time.sleep(PAUZA_SEGUNDE)

    print("\n============================================================", flush=True)
    print(f"🎉 UNIFORMIZARE STRUCTURĂ COMPLETĂ! Total fișiere redenumite: {redenumite_totale:,} în {formateaza_timp(time.time() - timp_start)}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
