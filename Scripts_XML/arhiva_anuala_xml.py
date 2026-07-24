import os
import sys
import json
import time
import re
import tarfile
from pathlib import Path

# Logare live instantanee (unbuffered output) pentru GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ==============================================================================
# CONFIGURARE CĂI
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from drive_config import FOLDERE_XML_IDS, get_file_params

# CONFIGURARE BATCH & PAUZĂ RATE LIMIT
DIMENSIUNE_BATCH = 100
PAUZA_SECUENTE_SEC = 2.5

# ==============================================================================
# PARAMETRI LANSARE
# ==============================================================================
if len(sys.argv) >= 3:
    AN_START, AN_END = int(sys.argv[1]), int(sys.argv[2])
elif len(sys.argv) == 2 and "-" in sys.argv[1]:
    pasi = sys.argv[1].split("-")
    AN_START, AN_END = int(pasi[0].strip()), int(pasi[1].strip())
elif len(sys.argv) == 2 and sys.argv[1].isdigit():
    AN_START = AN_END = int(sys.argv[1])
else:
    AN_START = AN_END = 1990


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


def Curata_parametri_google(params):
    chei_custom = ["drive_id", "tip_stocare", "arhiva", "cale_interna", "an", "pagina"]
    for k in chei_custom:
        params.pop(k, None)
    return params


def proceseaza_arhiva_pentru_an(service, an):
    print(f"\n============================================================", flush=True)
    print(f"📦 PORNIRE PROCESARE ARHIVĂ PENTRU ANUL: {an}", flush=True)
    print(f"============================================================", flush=True)

    pattern_nestandard = re.compile(
        r"(?:brut_legislatie|XML_legislatie|Brut_XML|XML_brut|legislatie_XML)_(\d+)_pag(\d+)\.xml", 
        re.IGNORECASE
    )

    # --------------------------------------------------------------------------
    # PAS 1: SCANARE ȘI REDENUMIRE DOAR PE FIȘIERELE CARE NU SUNT CORECTE
    # --------------------------------------------------------------------------
    print(f"🔍 [PAS 1] Scanare fișiere an {an} în cele {len(FOLDERE_XML_IDS)} Shared Drive-uri...", flush=True)
    fisiere_an = []
    
    total_redenumite_an = 0
    total_deja_corecte = 0
    actiuni_batch_curent = 0
    numar_batch = 1

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        page_token = None
        count_drive_fisiere = 0

        while True:
            try:
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false and name contains '_{an}_pag'",
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
                    match_nestandard = pattern_nestandard.match(nume_vechi)
                    m_generat = re.search(rf"_{an}_pag(\d+)", nume_vechi, re.IGNORECASE)

                    # 1. VERIFICARE: Este DEJA corect (ex: brut_XML_1990_pag1.xml)?
                    if nume_vechi.startswith(f"brut_XML_{an}_pag") and nume_vechi.endswith(".xml"):
                        fisiere_an.append({"id": f['id'], "name": nume_vechi})
                        count_drive_fisiere += 1
                        total_deja_corecte += 1
                        continue  # ⏩ NU REDENUMIM Nimic, Trecem Direct Peste!

                    # 2. DACA NU ESTE CORECT, ÎI APLICĂM NORMALIZE Numele
                    if match_nestandard or m_generat:
                        pag = match_nestandard.group(2) if match_nestandard else m_generat.group(1)
                        nume_nou = f"brut_XML_{an}_pag{pag}.xml"
                        
                        try:
                            service.files().update(
                                fileId=f['id'],
                                body={'name': nume_nou},
                                supportsAllDrives=True,
                                supportsTeamDrives=True
                            ).execute()
                            
                            total_redenumite_an += 1
                            actiuni_batch_curent += 1
                            print(f"   ✏️ [{total_redenumite_an:,}] Redenumit pe Drive {idx}: '{nume_vechi}' ➡️ '{nume_nou}'", flush=True)
                            
                            fisiere_an.append({"id": f['id'], "name": nume_nou})
                            count_drive_fisiere += 1

                            # PAUZĂ PACHET 100 REDENUMIRI
                            if actiuni_batch_curent >= DIMENSIUNE_BATCH:
                                print(f"\n☕ [BATCH {numar_batch} REDENUMIRI COMPLET] Pauză {PAUZA_SECUENTE_SEC}s...\n", flush=True)
                                time.sleep(PAUZA_SECUENTE_SEC)
                                numar_batch += 1
                                actiuni_batch_curent = 0

                        except Exception as e_red:
                            print(f"   ⚠️ Eroare redenumire {f['id']}: {e_red}", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except Exception as e:
                print(f"   ⚠️ Eroare la scanarea Drive {idx}: {e}", flush=True)
                break

        if count_drive_fisiere > 0:
            print(f"   📂 Drive [{idx}/{len(FOLDERE_XML_IDS)}]: Găsite {count_drive_fisiere:,} fișiere XML pt. anul {an}.", flush=True)

    total_fisiere = len(fisiere_an)
    print(f"\n✅ [PAS 1 COMPLET] Total fișiere an {an}: {total_fisiere:,} (Deja corecte: {total_deja_corecte:,} | Corectate: {total_redenumite_an:,})", flush=True)

    if total_fisiere == 0:
        print(f"ℹ️ Niciun fișier XML găsit pentru anul {an}. Se sare peste arhivare.", flush=True)
        return

    # --------------------------------------------------------------------------
    # PAS 2: DESCĂRCARE LOCALĂ ȘI COMPRESIE TAR.GZ
    # --------------------------------------------------------------------------
    dir_temp = RADACINA_PROIECT / f"temp_{an}"
    dir_temp.mkdir(parents=True, exist_ok=True)
    nume_arhiva_tar = f"brut_XML_{an}.tar.gz"
    cale_arhiva_local = RADACINA_PROIECT / nume_arhiva_tar

    print(f"\n📥 [PAS 2] Descărcare locală {total_fisiere:,} fișiere...", flush=True)
    for idx, f_info in enumerate(fisiere_an, start=1):
        cale_dest = dir_temp / f_info['name']
        try:
            req = service.files().get_media(fileId=f_info['id'], supportsAllDrives=True)
            continut = req.execute()
            with open(cale_dest, "wb") as f_out:
                f_out.write(continut)
                
            if idx % 200 == 0 or idx == total_fisiere:
                procent = (idx / total_fisiere) * 100
                print(f"   📥 Progres descărcare: [{idx:,}/{total_fisiere:,}] ({procent:.1f}%)", flush=True)
        except Exception as e_desc:
            print(f"   ⚠️ Eroare descărcare {f_info['name']}: {e_desc}", flush=True)

    print(f"\n📦 [PAS 3] Împachetare în arhivă GZIP: {nume_arhiva_tar}...", flush=True)
    t_arhiva = time.time()
    
    with tarfile.open(cale_arhiva_local, "w:gz") as tar:
        for f_path in dir_temp.glob("*.xml"):
            tar.add(f_path, arcname=f_path.name)

    dimensiune_mb = cale_arhiva_local.stat().st_size / (1024 * 1024)
    print(f"💾 Arhivă locală realizată în {time.time() - t_arhiva:.2f}s | Dimensiune: {dimensiune_mb:.2f} MB", flush=True)

    # --------------------------------------------------------------------------
    # PAS 3: STOCARE DINAMICĂ PE GOOGLE DRIVE (LOAD BALANCING)
    # --------------------------------------------------------------------------
    params_stocare = get_file_params(nume_arhiva_tar)
    folder_target_id = params_stocare.get("drive_id") or FOLDERE_XML_IDS[0]

    print(f"\n⬆️ [PAS 4] Încărcare arhivă {nume_arhiva_tar} pe Google Drive (Target ID: {folder_target_id})...", flush=True)
    try:
        media = MediaFileUpload(str(cale_arhiva_local), mimetype="application/gzip", resumable=True)
        file_metadata = {
            "name": nume_arhiva_tar,
            "parents": [folder_target_id],
            "mimeType": "application/gzip"
        }

        params = Curata_parametri_google(params_stocare)
        params["body"] = file_metadata
        params["media_body"] = media
        params["supportsAllDrives"] = True
        params["supportsTeamDrives"] = True

        res = service.files().create(**params).execute()
        print(f"✅ Arhivă {nume_arhiva_tar} încărcată cu succes pe Drive! [ID: {res.get('id')}]", flush=True)
    except Exception as e_up:
        print(f"❌ Eroare la upload-ul arhivei {nume_arhiva_tar}: {e_up}", flush=True)

    # Curățare fișiere locale temporare
    for f_p in dir_temp.glob("*.xml"):
        f_p.unlink()
    dir_temp.rmdir()
    if cale_arhiva_local.exists():
        cale_arhiva_local.unlink()

    print(f"🔒 Fișierele XML individuale originale AU FOST PĂSTRATE pe Google Drive.", flush=True)


def main():
    service = get_drive_service()
    for an in range(AN_START, AN_END + 1):
        proceseaza_arhiva_pentru_an(service, an)

if __name__ == "__main__":
    main()
