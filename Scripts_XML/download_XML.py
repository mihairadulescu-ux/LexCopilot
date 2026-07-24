import os
import sys
import json
import time
import urllib.request
from pathlib import Path

# Stream live unbuffered pentru GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DIRECTOR_CURENT = Path(__file__).resolve().parent
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from drive_config import FOLDERE_XML_IDS, get_file_params

PAUZA_SECUENTIALA = 0.5  # Pauză între cereri pentru a proteja serverul sursă


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
            print(f"❌ [AUTH] Eroare parsare Service Account JSON: {e}", flush=True)
            sys.exit(1)
            
    cale_local = DIRECTOR_CURENT / "service_account.json"
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


def descarca_si_salveaza_pagina(service, an_download, pagina, url_sursa):
    """
    Descarcă XML-ul și îl salvează STRICT după anul de download și numărul paginii,
    asigurând continuitate la reluarea rulărilor.
    """
    nume_fisier_final = f"brut_XML_{an_download}_pag{pagina}.xml"

    try:
        req = urllib.request.Request(
            url_sursa, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            continut_bytes = response.read()

        if len(continut_bytes.strip()) < 50:
            print(f"⚠️ [PAGINA {pagina}] Fișier XML gol sau invalid primit de la server.", flush=True)
            return False

        # Determinare Drive de stocare
        params_stocare = get_file_params(nume_fisier_final)
        folder_drive_id = params_stocare.get("drive_id") or FOLDERE_XML_IDS[0]

        # Salvare temporară locală pentru upload
        cale_temp = DIRECTOR_CURENT / nume_fisier_final
        with open(cale_temp, "wb") as f_temp:
            f_temp.write(continut_bytes)

        # Upload pe Google Drive
        media = MediaFileUpload(str(cale_temp), mimetype="text/xml", resumable=True)
        file_metadata = {
            "name": nume_fisier_final,
            "parents": [folder_drive_id]
        }

        service.files().create(
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True,
            supportsTeamDrives=True
        ).execute()

        # Ștergere temp local
        if cale_temp.exists():
            cale_temp.unlink()

        print(f"✅ Salvat: '{nume_fisier_final}' pe Drive ID: {folder_drive_id[:12]}...", flush=True)
        return True

    except Exception as e:
        print(f"❌ Eroare descărcare An {an_download} | Pagina {pagina}: {e}", flush=True)
        return False


def main():
    service = get_drive_service()

    # Utilizare: python download_xml.py <AN_DOWNLOAD> <PAGINA_START> <PAGINA_END>
    if len(sys.argv) >= 4 and sys.argv[1].isdigit() and sys.argv[2].isdigit() and sys.argv[3].isdigit():
        an_download = int(sys.argv[1])
        pag_start = int(sys.argv[2])
        pag_end = int(sys.argv[3])
    else:
        print("ℹ️ Utilizare: python download_xml.py <AN_DOWNLOAD> <PAGINA_START> <PAGINA_END>", flush=True)
        sys.exit(1)

    print("============================================================", flush=True)
    print(f"🚀 PORNIRE DESCĂRCARE AN {an_download} | PAGINILE {pag_start} ➡️ {pag_end}", flush=True)
    print("============================================================", flush=True)

    succese = 0
    for pag in range(pag_start, pag_end + 1):
        url = f"https://legislatie.just.ro/Public/DetaliiDocumentAfis/{pag}"
        
        ok = descarca_si_salveaza_pagina(service, an_download, pag, url)
        if ok:
            succese += 1
        time.sleep(PAUZA_SECUENTIALA)

    print(f"\n🏁 Finalizat! Descărcate cu succes {succese}/{pag_end - pag_start + 1} pagini pentru anul {an_download}.", flush=True)


if __name__ == "__main__":
    main()
