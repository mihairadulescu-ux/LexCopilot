import os
import sys
import json
import gzip
import time
import re
from pathlib import Path

# Logare live instantanee (unbuffered output)
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

NOME_INDEX_MASTER_LOCAL = "index_xml.json.gz"
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES")
XML_STORAGE_INDEX_ID = os.getenv("XML_STORAGE_INDEX")

if not XML_STORAGE_INDEX_ID:
    print("🛑 [EROARE CRITICĂ] Variabila 'XML_STORAGE_INDEX' nu este definită în mediu!", flush=True)
    sys.exit(1)


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


def Curata_parametri_google(params):
    chei_custom = ["drive_id", "tip_stocare", "arhiva", "cale_interna", "an", "pagina"]
    for k in chei_custom:
        params.pop(k, None)
    return params


def scaneaza_shared_drives_complet(service):
    """
    Scanează fizic de la zero toate cele 7 Shared Drive-uri XML.
    """
    t_start = time.time()
    print(f"\n🔍 [FULL SCAN] Pornire scanare fizică în cele {len(FOLDERE_XML_IDS)} Shared Drive-uri XML...", flush=True)
    master_dict = {}
    pattern = re.compile(r"brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml", re.IGNORECASE)

    total_fisiere_scanate = 0

    for idx, folder_id in enumerate(FOLDERE_XML_IDS, start=1):
        print(f"\n📂 [{idx}/{len(FOLDERE_XML_IDS)}] Scanare Shared Drive ID: {folder_id}", flush=True)
        page_token = None
        count_folder = 0
        pasi_pagina = 0

        while True:
            pasi_pagina += 1
            try:
                response = service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false and name contains 'brut_'",
                    spaces='drive',
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=1000,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True
                ).execute()

                files = response.get('files', [])
                for f in files:
                    nume = f['name']
                    match = pattern.match(nume)
                    if match:
                        an = int(match.group(1))
                        pagina = int(match.group(2))
                        nume_standard = f"brut_XML_{an}_pag{pagina}.xml"
                        
                        master_dict[nume_standard] = {
                            "an": an,
                            "pagina": pagina,
                            "tip_stocare": "individual",
                            "arhiva": None,
                            "cale_interna": None,
                            "drive_id": f['id']
                        }
                        count_folder += 1

                print(f"   ⏳ [Drive {idx}/{len(FOLDERE_XML_IDS)}] Pagina {pasi_pagina} interogată | +{len(files)} fișiere găsite (Total folder: {count_folder:,})", flush=True)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except Exception as e:
                print(f"   ⚠️ [Eroare Folder {folder_id}]: {e}", flush=True)
                break

        total_fisiere_scanate += count_folder
        print(f"   ✅ [Drive {idx}/{len(FOLDERE_XML_IDS)}] Finalizat! Total fișiere unice colectate: {count_folder:,}", flush=True)

    durata = time.time() - t_start
    print(f"\n🎉 [FULL SCAN COMPLET] Scanat în {durata:.2f}s | Total fișiere unice indexate: {len(master_dict):,}\n", flush=True)
    return master_dict


def colecteaza_toti_micro_indecsii(service, master_dict):
    """
    Caută și citește ABSOLUT TOȚI micro-indecșii neconsolidați (cu paginare completă).
    Returnează dicționarul actualizat și lista ID-urilor fișierelor care trebuie trimise la Trash.
    """
    if not FOLDER_TEMP_INDEXES_ID:
        print("ℹ️ [MICRO-INDEX] Variabila TEMPORARY_XML_INDEXES nu este definită. Se sare peste consolidare.", flush=True)
        return master_dict, []

    print(f"🔍 [MICRO-INDEX] Căutare paginată a TUTROR micro-indecșilor în folderul temp (ID: {FOLDER_TEMP_INDEXES_ID})...", flush=True)
    fisiere_temp_de_sters = []
    total_micro_gasite = 0
    page_token = None
    pagina_nr = 0

    while True:
        pagina_nr += 1
        try:
            rezultat = service.files().list(
                q=f"'{FOLDER_TEMP_INDEXES_ID}' in parents and trashed=false and name contains 'temp_index_'",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=1000,  # Preia până la 1.000 pe o singură pagină de API
                pageToken=page_token,
                fields="nextPageToken, files(id, name)"
            ).execute()

            micro_files = rezultat.get("files", [])
            if micro_files:
                print(f"   🧩 Pagina {pagina_nr} micro-indecși: Găsite {len(micro_files)} fișiere. Ingerare date...", flush=True)
                for idx, mf in enumerate(micro_files, start=1):
                    try:
                        req = service.files().get_media(
                            fileId=mf["id"],
                            supportsAllDrives=True
                        )
                        continut = req.execute()
                        date_micro = json.loads(continut.decode("utf-8"))
                        updates = date_micro.get("flag_updates", {})
                        
                        master_dict.update(updates)
                        fisiere_temp_de_sters.append(mf["id"])
                        total_micro_gasite += 1
                    except Exception as e:
                        print(f"   ⚠️ Eroare la procesarea micro-indexului {mf['name']}: {e}", flush=True)
            
            page_token = rezultat.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            print(f"⚠️ [MICRO-INDEX] Eroare la interogarea listei: {e}", flush=True)
            break

    print(f"✅ [MICRO-INDEX COMPLET] Au fost ingerați cu succes TOȚI cei {total_micro_gasite} micro-indecși găsiți!\n", flush=True)
    return master_dict, fisiere_temp_de_sters


def trimite_micro_indecsii_la_trash(service, lista_id_uri):
    """
    Trimite la Trash / Șterge absolut toți micro-indecșii care au fost procesați.
    """
    total = len(lista_id_uri)
    if total == 0:
        print("ℹ️ [TRASH] Nu există micro-indecși de curățat.", flush=True)
        return

    print(f"🧹 [TRASH] Se elimină / trimit la Trash TOȚI cei {total} micro-indecși procesați...", flush=True)
    curatati = 0
    for idx, fid in enumerate(lista_id_uri, start=1):
        try:
            # Mai întâi încercăm delete direct (hard delete)
            try:
                service.files().delete(fileId=fid, supportsAllDrives=True).execute()
            except Exception:
                # Fallback pentru Shared Drives / Content Manager: Move to Trash (trashed=True)
                service.files().update(
                    fileId=fid,
                    body={'trashed': True},
                    supportsAllDrives=True
                ).execute()
            curatati += 1

            if idx % 50 == 0 or idx == total:
                print(f"   🧹 Curățați {idx}/{total} micro-indecși...", flush=True)
        except Exception as e:
            pass

    print(f"✅ [TRASH COMPLET] Curățare finalizată! {curatati}/{total} micro-indecși eliminați de pe Drive.\n", flush=True)


def salveaza_si_urca_master_index_gz(service, master_dict):
    """Comprimă local în .json.gz și face UPDATE pe Google Drive."""
    print(f"📦 [COMPRESIE] Generare Master Index GZIP ({len(master_dict):,} intrări totale)...", flush=True)
    
    cale_local = Path(NOME_INDEX_MASTER_LOCAL)
    t_start = time.time()
    
    with gzip.open(cale_local, "wb") as f:
        json_bytes = json.dumps(master_dict, ensure_ascii=False, indent=2).encode("utf-8")
        f.write(json_bytes)
        
    dimensiune_mb = cale_local.stat().st_size / (1024 * 1024)
    print(f"💾 Arhivă locală creată în {time.time() - t_start:.2f}s | Dimensiune: {dimensiune_mb:.2f} MB", flush=True)

    print(f"⬆️ [UPLOAD] Actualizare Master Index pe Drive (ID: {XML_STORAGE_INDEX_ID})...", flush=True)
    try:
        media = MediaFileUpload(str(cale_local), mimetype="application/gzip", resumable=True)
        
        params = get_file_params(NOME_INDEX_MASTER_LOCAL)
        params = Curata_parametri_google(params)
        params["fileId"] = XML_STORAGE_INDEX_ID
        params["media_body"] = media
        params["supportsAllDrives"] = True
        params["supportsTeamDrives"] = True

        updated_file = service.files().update(**params).execute()
        print(f"✅ [UPLOAD REUȘIT] Master Index GZIP actualizat cu succes pe Drive! [ID: {updated_file.get('id')}]", flush=True)
        return True
    except Exception as e:
        print(f"❌ [UPLOAD EȘUAT] Eroare critică la actualizarea Master Index pe Drive: {e}", flush=True)
        return False
    finally:
        if cale_local.exists():
            cale_local.unlink()


def main():
    t_global = time.time()
    print("============================================================", flush=True)
    print("🏗️ ENGINE INDEXARE: SCANARE DRIVES + INGERARE MICRO-INDECȘI + TRASH CLEANUP", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()

    # 1. SCANARE RECURSIVĂ DE LA ZERO PE TOATE CELE 7 SHARED DRIVES
    master_dict = scaneaza_shared_drives_complet(service)

    # 2. INGERARE PAGINATĂ A TUTUROR MICRO-INDECȘILOR EXISTENȚI
    master_dict, temp_ids_de_sters = colecteaza_toti_micro_indecsii(service, master_dict)

    # 3. COMPRESIE GZIP ȘI UPLOAD PE DRIVE A NOULUI MASTER INDEX
    succes_upload = salveaza_si_urca_master_index_gz(service, master_dict)

    # 4. TRIMITEREA LA TRASH A TUTUROR MICRO-INDECȘILOR PROCESAȚI (DOAR DACĂ UPLOAD-UL A REUȘIT)
    if succes_upload:
        trimite_micro_indecsii_la_trash(service, temp_ids_de_sters)
    else:
        print("⚠️ [AVERTISMENT] Ștergerea micro-indecșilor a fost oprită deoarece salvarea pe Drive a eșuat!", flush=True)

    durata_totala = time.time() - t_global
    print("============================================================", flush=True)
    print(f"🏁 PROCES DE RE-INDEXARE ȘI CURĂȚARE FINALIZAT ÎN {durata_totala:.2f} SECUNDE!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
