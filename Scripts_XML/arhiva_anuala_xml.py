import os
import sys
import json
import time
import re
from pathlib import Path

# Stream live instant în GitHub Actions
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

DIMENSIUNE_BATCH = 100
PAUZA_SECUENTE_SEC = 2.5


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


def extrage_an_real_din_continut_xml(continut_str):
    """Extrage anul real al actului direct din tag-urile sau textul XML."""
    # 1. Tag-uri specifice de An
    m_tag = re.search(r"<(?:An|AnEmitere|AnPublicare|AnAparitie)>(\d{4})</", continut_str, re.IGNORECASE)
    if m_tag:
        return m_tag.group(1)

    # 2. Atribute de tip Data="YYYY-MM-DD"
    m_data = re.search(r'(?:Data|DataEmitere|DataAparitie|DataPublicarii)=["\'](\d{4})-\d{2}-\d{2}', continut_str, re.IGNORECASE)
    if m_data:
        return m_data.group(1)

    # 3. Anul menționat în text "din YYYY" sau "nr. ... / YYYY"
    m_text = re.search(r"(?:din|anul)\s+(19\d\d|20\d\d)", continut_str, re.IGNORECASE)
    if m_text:
        return m_text.group(1)

    # 4. Fallback: orice an de 4 cifre valid între 1800 și 2026 găsit în XML
    m_gen = re.search(r"\b(18\d\d|19\d\d|20[0-2]\d)\b", continut_str)
    if m_gen:
        return m_gen.group(1)

    return None


def redenumeste_fisiere_pe_drive():
    print("============================================================", flush=True)
    print("🔍 AUDIT & REDENUMIRE TOTALĂ: VERIFICARE CONȚINUT XML LA FIECARE FIȘIER", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()

    pattern_pag = re.compile(r"_pag(\d+)\.xml", re.IGNORECASE)

    total_evaluate = 0
    total_deja_perfecte = 0
    total_redenumite = 0
    total_fara_an = 0
    actiuni_in_batch_curent = 0
    numar_batch = 1

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n📂 [{idx}/{len(FOLDERE_XML_IDS)}] Scanare completă Shared Drive ID: {folder_id}...", flush=True)
        page_token = None
        count_drive_redenumite = 0

        while True:
            try:
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false and name contains '.xml'",
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
                    total_evaluate += 1

                    # Extragem numărul paginii din nume
                    m_pag = pattern_pag.search(nume_vechi)
                    if not m_pag:
                        continue
                    pagina = m_pag.group(1)

                    # CITIM PRIMII KILOOCTEȚI DIN CONȚINUTUL FIȘIERULUI
                    try:
                        req = service.files().get_media(fileId=f['id'], supportsAllDrives=True)
                        # Descărcăm doar primii 4KB pentru eficiență maximă
                        req.headers['Range'] = 'bytes=0-4096'
                        continut_bytes = req.execute()
                        continut_str = continut_bytes.decode('utf-8', errors='ignore')
                        an_real = extrage_an_real_din_continut_xml(continut_str)
                    except Exception as e_read:
                        # Fallback dacă serverul refuză Range request
                        try:
                            req = service.files().get_media(fileId=f['id'], supportsAllDrives=True)
                            continut_bytes = req.execute()
                            continut_str = continut_bytes.decode('utf-8', errors='ignore')
                            an_real = extrage_an_real_din_continut_xml(continut_str)
                        except Exception:
                            print(f"   ⚠️ Nu s-a putut citi conținutul fișierului {nume_vechi}", flush=True)
                            continue

                    if not an_real:
                        total_fara_an += 1
                        continue

                    nume_nou_standard = f"brut_XML_{an_real}_pag{pagina}.xml"

                    # DĂCĂ DEJA CORESPUNDE 100%, IL IGNORĂM
                    if nume_vechi == nume_nou_standard:
                        total_deja_perfecte += 1
                        if total_evaluate % 500 == 0:
                            print(f"   ⏳ Verificate {total_evaluate:,} fișiere | Corectate până acum: {total_redenumite:,}", flush=True)
                        continue

                    # REDENUMIRE PE DRIVE PENTRU CELE NEINCONFORMĂ
                    try:
                        service.files().update(
                            fileId=f['id'],
                            body={'name': nume_nou_standard},
                            supportsAllDrives=True,
                            supportsTeamDrives=True
                        ).execute()

                        total_redenumite += 1
                        count_drive_redenumite += 1
                        actiuni_in_batch_curent += 1

                        print(f"   ✏️ [{total_redenumite:,}] Corectat: '{nume_vechi}' ➡️ '{nume_nou_standard}' (An din XML: {an_real})", flush=True)

                        # BATCH PAUSE (100 acțiuni)
                        if actiuni_in_batch_curent >= DIMENSIUNE_BATCH:
                            print(f"\n☕ [BATCH {numar_batch} COMPLET] Am procesat 100 redenumiri. Pauză de {PAUZA_SECUENTE_SEC}s...\n", flush=True)
                            time.sleep(PAUZA_SECUENTE_SEC)
                            numar_batch += 1
                            actiuni_in_batch_curent = 0

                    except Exception as e_red:
                        print(f"   ⚠️ Eroare redenumire {f['id']} ({nume_vechi}): {e_red}", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Eroare la scanarea folderului {folder_id}: {e}", flush=True)
                break

        print(f"✅ Drive {idx} finalizat! Corectate în acest folder: {count_drive_redenumite:,}", flush=True)

    print("\n============================================================", flush=True)
    print(f"🏁 REPARARE & AUDIT TOTAL FINALIZAT!", flush=True)
    print(f"📊 Evaluat: {total_evaluate:,} | De la început corecte: {total_deja_perfecte:,} | Corectate din XML: {total_redenumite:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    redenumeste_fisiere_pe_drive()
