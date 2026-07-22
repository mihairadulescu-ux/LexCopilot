import os
import sys
import time
import json
from pathlib import Path

# ==============================================================================
# CONFIGURARE CĂI DE IMPORT
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from drive_config import get_file_params

try:
    import XML_INDEX_READER
except ImportError:
    from Scripts_XML import XML_INDEX_READER

INDEX_FILE_ID = os.getenv("XML_STORAGE_INDEX") or "1OkPgwX_F6FKwupuhD9kO3rynj4zdel0N"


def get_drive_service():
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
    if creds_json:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    
    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        creds = service_account.Credentials.from_service_account_file(
            str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
        
    print("❌ Secretul Google Drive nu a fost găsit!")
    sys.exit(1)


def main():
    print("============================================================", flush=True)
    print("🔄 REPATRIERE/REDENUMIRE FIȘIERE PE GOOGLE DRIVE", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()
    
    print("\n1️⃣ Încărcare Index Virtual...", flush=True)
    index_v = XML_INDEX_READER.obtine_index_virtual(service)
    fisiere_map = index_v.get("fisiere", {})

    fisiere_de_redenumit = []

    for nume_vechi, meta in fisiere_map.items():
        if nume_vechi.startswith("brut_legislatie_"):
            nume_nou = nume_vechi.replace("brut_legislatie_", "brut_XML_")
            fisiere_de_redenumit.append({
                "id": meta["id"],
                "nume_vechi": nume_vechi,
                "nume_nou": nume_nou
            })

    if not fisiere_de_redenumit:
        print("✨ Nu există fișiere cu formatul vechi 'brut_legislatie_'. Totul este deja redenumit!", flush=True)
        return

    print(f"📊 Am găsit {len(fisiere_de_redenumit):,} fișiere de redenumit.", flush=True)
    print(f"Exemplu: {fisiere_de_redenumit[0]['nume_vechi']} ➡️ {fisiere_de_redenumit[0]['nume_nou']}\n", flush=True)

    redenumite_cu_succes = 0
    timp_start = time.time()

    for idx, item in enumerate(fisiere_de_redenumit, start=1):
        file_id = item["id"]
        nume_nou = item["nume_nou"]
        nume_vechi = item["nume_vechi"]

        for incercare in range(3):
            try:
                params = get_file_params(fileId=file_id)
                params["body"] = {"name": nume_nou}
                service.files().update(**params).execute()
                
                # Actualizăm și în memoria Master Index-ului
                if nume_vechi in fisiere_map:
                    data_meta = fisiere_map.pop(nume_vechi)
                    fisiere_map[nume_nou] = data_meta

                redenumite_cu_succes += 1
                break
            except Exception as e:
                time.sleep(1)

        if idx % 500 == 0 or idx == len(fisiere_de_redenumit):
            durata = round(time.time() - timp_start, 1)
            ritm = round(idx / (durata if durata > 0 else 1), 1)
            print(f"⚡ [Redenumire Drive] Redenumite {idx:,}/{len(fisiere_de_redenumit):,} fișiere | Ritm: {ritm} f/sec", flush=True)

    print("\n============================================================", flush=True)
    print(f"🎉 REDENUMIRE COMPLETĂ! Total fișiere actualizate: {redenumite_cu_succes:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
