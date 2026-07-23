import sys
import os
import time
import json
import socket
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Standardul pentru loguri vizibile live în GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def print_log(msg):
    print(msg, flush=True)
    sys.stdout.flush()

print_log("============================================================")
print_log("🏷️ REDENUMIRE RAPIDĂ DIN INDEX MASTER (brut_legislatie -> brut_XML)")
print_log("============================================================")

socket.setdefaulttimeout(30)

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build

from drive_config import get_file_params
from XML_INDEX_READER import creeaza_cititor_index

BATCH_SIZE = 2000       # Raportăm progresul la fiecare 2.000 de redenumiri
MAX_WORKERS = 15        # 15 conexiuni paralele simultane către Drive API


def get_drive_service():
    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )

    if not creds_json:
        print_log("❌ NU S-A GĂSIT SECRETUL GOOGLE_SERVICE_ACCOUNT_JSON!")
        sys.exit(1)

    try:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print_log(f"❌ Eroare la autentificare: {e}")
        sys.exit(1)


def redenumeste_fisier_individual(item):
    """Efectuează redenumirea unui singur fișier pe Drive."""
    service = get_drive_service()
    for incercare in range(3):
        try:
            params = get_file_params(fileId=item["id"])
            params["body"] = {"name": item["nume_nou"]}
            service.files().update(**params).execute()
            return True
        except Exception:
            time.sleep(0.5)
    return False


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
    print_log("📥 Încărcăm indexul principal din cloud...")
    reader = creeaza_cititor_index()
    index_data = reader.incarca_index()

    fisiere_de_redenumit = []
    pattern_vechi = re.compile(r"^brut_legislatie_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)

    # Interogăm direct indexul aflat în memorie (fără scanat pe Drive!)
    print_log("⚙️ Analizăm fișierele din indexul master...")
    for cheie, fisier in index_data.items():
        nume_actual = fisier.get("name", "")
        file_id = fisier.get("id")

        match = pattern_vechi.match(nume_actual)
        if match and file_id:
            nume_nou = f"brut_XML_{match.group(1)}_pag{match.group(2)}.xml"
            fisiere_de_redenumit.append({
                "id": file_id,
                "nume_vechi": nume_actual,
                "nume_nou": nume_nou
            })

    total_initial = len(fisiere_de_redenumit)

    if not total_initial:
        print_log("\n✨ FELICITĂRI! Toate fișierele din index au deja denumirea standard brut_XML_!")
        return

    print_log(f"\n📊 AU FOST IDENTIFICATE {total_initial:,} FIȘIERE LEGACY PENTRU REDENUMIRE!")
    print_log(f"⚡ Începem redenumirea PARALELĂ pe {MAX_WORKERS} conexiuni...\n")

    redenumite_totale = 0
    timp_start = time.time()

    while fisiere_de_redenumit:
        lot_curent = fisiere_de_redenumit[:BATCH_SIZE]
        fisiere_de_redenumit = fisiere_de_redenumit[BATCH_SIZE:]

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(redenumeste_fisier_individual, item)
                for item in lot_curent
            ]
            for future in as_completed(futures):
                if future.result():
                    redenumite_totale += 1

        durata_cumulata = time.time() - timp_start
        viteză_medie = redenumite_totale / durata_cumulata if durata_cumulata > 0 else 0
        
        fisiere_ramase = total_initial - redenumite_totale
        eta_secunde = (fisiere_ramase / viteză_medie) if viteză_medie > 0 else 0

        bara = genereaza_bara_progres(redenumite_totale, total_initial)
        
        print_log(f"🏷️ BATCH PARALEL EXECUTAT: {redenumite_totale:,}/{total_initial:,}")
        print_log(f"   ├─ Progres: {bara}")
        print_log(f"   ├─ Viteză: {viteză_medie:.1f} redenumiri/secundă")
        print_log(f"   └─ ETA: {formateaza_timp(eta_secunde)}")
        print_log("------------------------------------------------------------")

    print_log("\n============================================================")
    print_log(f"🎉 UNIFORMIZARE STRUCTURĂ COMPLETĂ! Total redenumite: {redenumite_totale:,} în {formateaza_timp(time.time() - timp_start)}")
    print_log("============================================================")


if __name__ == "__main__":
    main()
