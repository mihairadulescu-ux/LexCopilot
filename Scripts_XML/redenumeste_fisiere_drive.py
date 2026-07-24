import os
import sys
import json
import time
import re
from pathlib import Path

# Force unbuffered output pentru log-uri LIVE
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

from drive_config import FOLDERE_XML_IDS


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
            print(f"❌ [AUTH] Eroare la parsarea JSON Service Account: {e}", flush=True)
            sys.exit(1)
            
    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ [AUTH] Eroare citire service_account.json local: {e}", flush=True)

    print("❌ [AUTH] Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


def redenumeste_fisiere_pe_drive():
    print("============================================================", flush=True)
    print("🔄 UTILITAR REDENUMIRE STANDARD FISIERE XML PE GOOGLE DRIVE", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()

    # Pattern pentru detectarea numelor greșite / nestandardizate
    # Exemple detectate: brut_legislatie_1990_pag1.xml, XML_legislatie_1990_pag1.xml, Brut_XML_1990_pag1.xml etc.
    pattern_gresit = re.compile(
        r"(?:brut_legislatie|XML_legislatie|Brut_XML|XML_brut|legislatie_XML)_(\d+)_pag(\d+)\.xml", 
        re.IGNORECASE
    )

    total_redenumite = 0

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n📂 [{idx}/{len(FOLDERE_XML_IDS)}] Scanare Shared Drive ID: {folder_id}...", flush=True)
        page_token = None
        count_drive = 0

        while True:
            try:
                # Căutăm fișierele din folder care conțin XML sau legislatie
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false and (name contains 'legislatie' or name contains 'Brut' or name contains 'XML')",
                    spaces='drive',
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=1000,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = response.get('files', [])
                for f in files:
                    nume_vechi = f['name']
                    match = pattern_gresit.match(nume_vechi)

                    # Dacă numele nu este cel standard "brut_XML_AN_pagPAGINA.xml"
                    if match or (nume_vechi.startswith("brut_XML_") and not nume_vechi.startswith("brut_XML_")):
                        if match:
                            an = match.group(1)
                            pagina = match.group(2)
                        else:
                            # Re-extraserem an si pagina daca e doar o diferență de majuscule/minuscule
                            m2 = re.search(r"(\d+)_pag(\d+)", nume_vechi, re.IGNORECASE)
                            if not m2:
                                continue
                            an, pagina = m2.group(1), m2.group(2)

                        nume_nou_standard = f"brut_XML_{an}_pag{pagina}.xml"

                        # Dacă numele de pe Drive diferă de cel standardizat
                        if nume_vechi != nume_nou_standard:
                            try:
                                service.files().update(
                                    fileId=f['id'],
                                    body={'name': nume_nou_standard},
                                    supportsAllDrives=True,
                                    supportsTeamDrives=True
                                ).execute()

                                print(f"   ✏️ Redenumit: '{nume_vechi}' ➡️ '{nume_nou_standard}'", flush=True)
                                count_drive += 1
                                total_redenumite += 1
                            except Exception as e_red:
                                print(f"   ⚠️ Eroare redenumire {f['id']} ({nume_vechi}): {e_red}", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Eroare la scanarea folderului {folder_id}: {e}", flush=True)
                break

        print(f"✅ Finalizat Drive {idx}! Total redenumite în acest folder: {count_drive}", flush=True)

    print("\n============================================================", flush=True)
    print(f"🏁 REDENUMIRE FINALIZATĂ! Total fișiere corectate pe Drive: {total_redenumite}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    redenumeste_fisiere_pe_drive()
