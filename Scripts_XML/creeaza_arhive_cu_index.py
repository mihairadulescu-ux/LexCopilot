import os
import sys
import json
import time
import tarfile
import gzip
import re
from pathlib import Path
from collections import defaultdict

# Stream live unbuffered pentru GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

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

FILE_INDEX_LOCAL = RADACINA_PROIECT / "index_xml.json.gz"

AN_TINTA = None
if len(sys.argv) >= 2 and sys.argv[1].isdigit():
    AN_TINTA = int(sys.argv[1])


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


def incarcare_index_master():
    """Încarcă indexul curent sau creează unul nou gol."""
    if FILE_INDEX_LOCAL.exists():
        try:
            with gzip.open(FILE_INDEX_LOCAL, "rt", encoding="utf-8") as f:
                print(f"📖 S-a încărcat indexul master existent ({FILE_INDEX_LOCAL.name}).", flush=True)
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Eroare la citirea index_xml.json.gz: {e}. Se va crea un index nou.", flush=True)
    return {}


def salvare_index_master(index_data):
    """Salvează starea actualizată a indexului comprimat gzip."""
    with gzip.open(FILE_INDEX_LOCAL, "wt", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    print(f"💾 Index master actualizat și salvat local ({FILE_INDEX_LOCAL.name}).", flush=True)


def proceseaza_si_arhiveaza_an(service, an, lista_fisiere, index_master):
    nume_arhiva = f"brut_XML_{an}.tar.gz"
    print(f"\n============================================================", flush=True)
    print(f"📦 PROCESARE & ARHIVARE ANUL {an}: {len(lista_fisiere):,} fișiere", flush=True)
    print(f"============================================================", flush=True)

    dir_temp = RADACINA_PROIECT / f"temp_arhivare_{an}"
    dir_temp.mkdir(parents=True, exist_ok=True)
    cale_arhiva_local = RADACINA_PROIECT / nume_arhiva

    total = len(lista_fisiere)
    print(f"📥 Descărcare temporară {total:,} fișiere...", flush=True)
    
    fisiere_descarcate_cu_succes = []

    for idx, f_info in enumerate(lista_fisiere, start=1):
        cale_dest = dir_temp / f_info['name']
        try:
            req = service.files().get_media(fileId=f_info['id'], supportsAllDrives=True)
            continut = req.execute()
            with open(cale_dest, "wb") as f_out:
                f_out.write(continut)
            
            fisiere_descarcate_cu_succes.append(f_info)
                
            if idx % 500 == 0 or idx == total:
                print(f"   📥 Descărcat: {idx:,}/{total:,} ({(idx/total)*100:.1f}%)", flush=True)
        except Exception as e_desc:
            print(f"   ⚠️ Eroare descărcare {f_info['name']}: {e_desc}", flush=True)

    if not fisiere_descarcate_cu_succes:
        print(f"⚠️ Niciun fișier descărcat cu succes pentru anul {an}. Abandonare arhivă.", flush=True)
        return

    # Împachetarea în arhiva TAR.GZ
    print(f"📦 Împachetare în {nume_arhiva}...", flush=True)
    t_start = time.time()
    with tarfile.open(cale_arhiva_local, "w:gz") as tar:
        for f_path in dir_temp.glob("*.xml"):
            tar.add(f_path, arcname=f_path.name)

    dim_mb = cale_arhiva_local.stat().st_size / (1024 * 1024)
    print(f"💾 Arhivă realizată în {time.time() - t_start:.2f}s | Dimensiune: {dim_mb:.2f} MB", flush=True)

    # Upload arhivă pe Drive
    params_stocare = get_file_params(nume_arhiva)
    folder_target_id = params_stocare.get("drive_id") or FOLDERE_XML_IDS[0]

    print(f"⬆️ Upload arhivă {nume_arhiva} pe Google Drive...", flush=True)
    arhiva_drive_id = None
    try:
        media = MediaFileUpload(str(cale_arhiva_local), mimetype="application/gzip", resumable=True)
        file_metadata = {
            "name": nume_arhiva,
            "parents": [folder_target_id],
            "mimeType": "application/gzip"
        }

        res = service.files().create(
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True,
            supportsTeamDrives=True
        ).execute()

        arhiva_drive_id = res.get('id')
        print(f"✅ Arhivă creată pe Drive! ID: {arhiva_drive_id}", flush=True)
    except Exception as e_up:
        print(f"❌ Eroare upload arhivă {nume_arhiva}: {e_up}", flush=True)

    # ACTUALIZARE INDEX MASTER CU METADATELE DE ARHIVĂ (FĂRĂ ȘTERGERE)
    print(f"📝 Actualizare status arhivă în indexul master...", flush=True)
    for f_info in fisiere_descarcate_cu_succes:
        key = f_info['name']  # Numele fișierului XML servește drept cheie
        
        if key not in index_master:
            index_master[key] = {
                "file_id": f_info['id'],
                "nume_fisier": f_info['name'],
                "folder_id": f_info.get('folder_id')
            }
        
        # Adăugăm starea de arhivare
        index_master[key]["status_arhiva"] = "arhivat"
        index_master[key]["nume_arhiva"] = nume_arhiva
        index_master[key]["arhiva_drive_id"] = arhiva_drive_id
        index_master[key]["cale_interna_arhiva"] = f_info['name']

    # Curățare temporare locale
    for f_p in dir_temp.glob("*.xml"):
        f_p.unlink()
    dir_temp.rmdir()
    if cale_arhiva_local.exists():
        cale_arhiva_local.unlink()


def main():
    service = get_drive_service()
    index_master = incarcare_index_master()

    pattern_xml = re.compile(r"brut_XML_(\d{4})_pag\d+\.xml", re.IGNORECASE)
    fisiere_per_an = defaultdict(list)

    print("============================================================", flush=True)
    print("🔍 SCENARE GOOGLE DRIVE PENTRU IDENTIFICARE FIȘIERE", flush=True)
    print("============================================================", flush=True)

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        page_token = None
        count_drive = 0

        while True:
            try:
                q_str = f"'{folder_id}' in parents and trashed=false and name contains 'brut_XML_'"
                if AN_TINTA:
                    q_str += f" and name contains 'brut_XML_{AN_TINTA}_'"

                response = service.files().list(
                    q=q_str,
                    spaces='drive',
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=1000,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = response.get('files', [])
                for f in files:
                    m = pattern_xml.match(f['name'])
                    if m:
                        an = int(m.group(1))
                        fisiere_per_an[an].append({
                            "id": f['id'], 
                            "name": f['name'],
                            "folder_id": folder_id
                        })
                        count_drive += 1

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except Exception as e:
                print(f"⚠️ Eroare la scanare Drive #{idx}: {e}", flush=True)
                break

        print(f"   📂 Drive [{idx}/{len(FOLDERE_XML_IDS)}]: Identificate {count_drive:,} fișiere.", flush=True)

    ani_de_procesat = sorted(list(fisiere_per_an.keys()))
    print(f"\n📊 Total ani găsiți pentru arhivare: {len(ani_de_procesat)}: {ani_de_procesat}", flush=True)

    for an in ani_de_procesat:
        lista_fisiere = fisiere_per_an[an]
        if lista_fisiere:
            proceseaza_si_arhiveaza_an(service, an, lista_fisiere, index_master)
            # Salvare intermediară a indexului după fiecare an procesat cu succes
            salvare_index_master(index_master)

    print("\n============================================================", flush=True)
    print("🏁 PROCES COMPLET FINALIZAT! NICIUN FIȘIER BRUT NU A FOST ȘTERS.", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
