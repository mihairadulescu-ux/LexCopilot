import os
import sys
import json
import time
import re
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

PAUZA_SECUENTIALA = 0.5  # Secunde între descărcări pentru a nu bloca serverul sursă


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


def extrage_an_real_din_xml(continut_str, an_fallback=None):
    """
    Scanează conținutul XML descărcat pentru a găsi anul real al actului.
    Dacă nu găsește niciun an în XML, folosește an_fallback.
    """
    # 1. Căutare în tag-urile specifice de an
    m_tag = re.search(r"<(?:An|AnEmitere|AnPublicare|AnAparitie)>(\d{4})</", continut_str, re.IGNORECASE)
    if m_tag:
        return m_tag.group(1)

    # 2. Căutare în atribute de dată (ex: Data="2004-05-12")
    m_data = re.search(r'(?:Data|DataEmitere|DataAparitie|DataPublicarii)=["\'](\d{4})-\d{2}-\d{2}', continut_str, re.IGNORECASE)
    if m_data:
        return m_data.group(1)

    # 3. Căutare în textul actului (ex: "din anul 2004", "din 1993")
    m_text = re.search(r"(?:din|anul)\s+(19\d\d|20\d\d)", continut_str, re.IGNORECASE)
    if m_text:
        return m_text.group(1)

    # 4. Orice an valid cu 4 cifre
    m_gen = re.search(r"\b(18\d\d|19\d\d|20[0-2]\d)\b", continut_str)
    if m_gen:
        return m_gen.group(1)

    return str(an_fallback) if an_fallback else "0000"


def descarca_si_salveaza_pagina(service, pagina, url_sursa, an_implicit=None):
    """
    Descarcă XML-ul de la URL, extrage anul real, îi dă numele corect
    și îl încarcă direct pe unul din cele 7 Shared Drive-uri.
    """
    try:
        req = urllib.request.Request(
            url_sursa, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            continut_bytes = response.read()

        continut_str = continut_bytes.decode('utf-8', errors='ignore')

        if len(continut_str.strip()) < 50:
            print(f"⚠️ [PAGINA {pagina}] Fișier XML gol sau invalid primit de la server.", flush=True)
            return False

        # EXTRAGERE AN REAL DIN XML
        an_real = extrage_an_real_din_xml(continut_str, an_fallback=an_implicit)

        # GENERARE NUME CONFORM SINTAXEI STANDARD
        nume_fisier_final = f"brut_XML_{an_real}_pag{pagina}.xml"

        # Determinare Drive de stocare (folosind configurația din drive_config)
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

        # Ștergere fișier temporar local
        if cale_temp.exists():
            cale_temp.unlink()

        print(f"✅ Descărcat & Salvat: '{nume_fisier_final}' pe Drive ID: {folder_drive_id[:12]}...", flush=True)
        return True

    except Exception as e:
        print(f"❌ Eroare la procesarea paginii {pagina}: {e}", flush=True)
        return False


def main():
    service = get_drive_service()

    # Exemplu utilizare din linia de comandă: python download_xml.py <PAGINA_START> <PAGINA_END>
    if len(sys.argv) >= 3 and sys.argv[1].isdigit() and sys.argv[2].isdigit():
        pag_start = int(sys.argv[1])
        pag_end = int(sys.argv[2])
    else:
        print("ℹ️ Utilizare: python download_xml.py <PAGINA_START> <PAGINA_END>", flush=True)
        sys.exit(1)

    print("============================================================", flush=True)
    print(f"🚀 PORNIRE DESCĂRCARE XML PENTRU PAGINILE {pag_start} ➡️ {pag_end}", flush=True)
    print("============================================================", flush=True)

    succese = 0
    for pag in range(pag_start, pag_end + 1):
        # Format URL sursă (ajustează URL-ul exact dacă folosești alt endpoint)
        url = f"https://legislatie.just.ro/Public/DetaliiDocumentAfis/{pag}"
        
        ok = descarca_si_salveaza_pagina(service, pag, url)
        if ok:
            succese += 1
        time.sleep(PAUZA_SECUENTIALA)

    print(f"\n🏁 Finalizat! Descărcate cu succes {succese}/{pag_end - pag_start + 1} pagini.", flush=True)


if __name__ == "__main__":
    main()
