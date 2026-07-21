import os
import sys
import time
import json
import requests
from pathlib import Path

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
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

from drive_config import (
    FOLDERE_XML_IDS,
    FOLDER_TEMP_INDEXES_ID,
    get_file_params,
    get_list_params,
)

try:
    import XML_INDEX_READER
except ImportError:
    from Scripts_XML import XML_INDEX_READER


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API
# ==============================================================================
def get_drive_service():
    """Autentificare în Google Drive API folosind GOOGLE_SERVICE_ACCOUNT_JSON."""
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
            print(f"❌ Eroare la citirea secretului JSON: {e}", flush=True)
            sys.exit(1)

    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare la citirea fișierului local service_account.json: {e}", flush=True)

    print("❌ Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


# ==============================================================================
# INTEROGARE API JUST.RO CU LOGGING ULTRA-DETALIAT PE ERORI
# ==============================================================================
def interogheaza_just_ro(an, pagina):
    """
    Efectuează cererea către API-ul Just.ro și oferă detalii diagnostice complete
    în caz de erori, fișiere nule sau răspunsuri invalide.
    """
    url = "https://legislatie.just.ro/api/Search/GetLegi"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LexCopilot/1.0"
    }
    
    payload = {
        "SearchAn": str(an),
        "NumarPagina": pagina,
        "RezultatePagina": 10
    }

    for incercare in range(1, 4):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            status = response.status_code
            text_raw = response.text or ""

            if status == 200:
                # Verificare calitate răspuns
                if not text_raw.strip():
                    print(f"⚠️ [An {an} | Pag {pagina}] Răspuns GOL (0 octeți) de la Just.ro! (Încercarea {incercare}/3)", flush=True)
                    time.sleep(2)
                    continue

                # Verificăm dacă structura conține date utile
                has_legi = "<Legi>" in text_raw or '"Legi":' in text_raw or "SearchModel" in text_raw
                if not has_legi:
                    print(
                        f"⚠️ [An {an} | Pag {pagina}] Răspuns HTTP 200 dar FĂRĂ date legislative valide!\n"
                        f"   ├─ Payload trimis: {payload}\n"
                        f"   └─ Fragment răspuns (primele 300 caractere):\n{text_raw[:300]}\n",
                        flush=True,
                    )
                return text_raw

            else:
                # Logare extinsă pentru coduri de eroare HTTP (404, 500, 503 etc.)
                print(
                    f"❌ [An {an} | Pag {pagina}] Eroare HTTP Status {status}! (Încercarea {incercare}/3)\n"
                    f"   ├─ URL: {url}\n"
                    f"   ├─ Payload: {payload}\n"
                    f"   ├─ Antete răspuns: {dict(response.headers)}\n"
                    f"   └─ Corp răspuns (primele 500 caractere):\n{text_raw[:500]}\n",
                    flush=True,
                )

        except requests.exceptions.Timeout:
            print(f"⌛ [An {an} | Pag {pagina}] TIMEOUT la conectarea la Just.ro (30s exspirat). Încercarea {incercare}/3", flush=True)
        except requests.exceptions.RequestException as req_err:
            print(f"❌ [An {an} | Pag {pagina}] Excepție de rețea/conexiune: {req_err} (Încercarea {incercare}/3)", flush=True)

        time.sleep(2.5 * incercare)

    print(f"💥 [An {an} | Pag {pagina}] Toate cele 3 încercări către Just.ro au eșuat definitiv!", flush=True)
    return None


# ==============================================================================
# SALVARE MICRO-INDEX TEMPORAR DUPĂ DESCARCARE
# ==============================================================================
def salveaza_micro_index(service, flag_updates):
    """Salvează un fișier temporar de update pentru a fi consolidat ulterior în Master Index."""
    if not flag_updates:
        return

    nume_temp = f"temp_index_download_{int(time.time())}.json"
    cale_temp = f"/tmp/{nume_temp}" if os.name != "nt" else nume_temp

    with open(cale_temp, "w", encoding="utf-8") as f:
        json.dump({"flag_updates": flag_updates}, f, ensure_ascii=False)

    try:
        media = MediaFileUpload(cale_temp, mimetype="application/json")
        file_metadata = {
            "name": nume_temp,
            "parents": [FOLDER_TEMP_INDEXES_ID]
        }
        
        params = get_file_params()
        params["body"] = file_metadata
        params["media_body"] = media
        
        service.files().create(**params).execute()
        print(f"🧩 [Micro-Index] Salvat cu succes update pentru {len(flag_updates)} fișiere noi.", flush=True)
    except Exception as e:
        print(f"⚠️ Eroare la salvarea micro-indexului temporar: {e}", flush=True)
    finally:
        if os.path.exists(cale_temp):
            os.remove(cale_temp)


# ==============================================================================
# PROCESARE AN
# ==============================================================================
def proceseaza_an(service, master_index_dict, an):
    print(f"\n📅 --- Începere verificare/descărcare pentru ANUL {an} ---", flush=True)
    
    folder_tinta_id = FOLDERE_XML_IDS[0] 

    pagina = 1
    fisiere_noi_descarcate = 0
    flag_updates_locala = {}

    while True:
        nume_xml = f"brut_legislatie_{an}_pag{pagina}.xml"

        # Check rapid în Master Index-ul aflat în memorie
        if nume_xml in master_index_dict:
            pagina += 1
            continue

        print(f"🔍 [Verificare] Pagina {pagina} pentru anul {an} nu există în index. Interogare API...", flush=True)
        continut_xml = interogheaza_just_ro(an, pagina)

        # Analiză detaliată a conținutului primit
        if not continut_xml:
            print(f"🛑 [Diagnostic] Răspuns nul/eșuat de la API. Se oprește căutarea pentru anul {an} la pagina {pagina}.", flush=True)
            break

        # Verificăm dacă răspunsul indică sfârșitul listei de legi
        are_legi = "<Legi>" in continut_xml or '"Legi":' in continut_xml or "SearchModel" in continut_xml
        if not are_legi:
            print(
                f"🏁 [Diagnostic] S-a atins capătul datelor pentru anul {an} la pagina {pagina}.\n"
                f"   └─ Motiv: Răspunsul primit nu mai conține acte normative (`Legi` / `SearchModel`).",
                flush=True
            )
            break

        # Salvare fișier XML în Shared Drive
        cale_temp_xml = f"/tmp/{nume_xml}" if os.name != "nt" else nume_xml
        with open(cale_temp_xml, "w", encoding="utf-8") as f:
            f.write(continut_xml)

        try:
            media = MediaFileUpload(cale_temp_xml, mimetype="text/xml")
            file_metadata = {
                "name": nume_xml,
                "parents": [folder_tinta_id]
            }
            params = get_file_params()
            params["body"] = file_metadata
            params["media_body"] = media
            
            res_file = service.files().create(**params).execute()
            file_id = res_file.get("id")

            meta_fisier = {
                "id": file_id,
                "folder_id": folder_tinta_id,
                "an": an,
                "pagina": pagina,
                "downloaded": True,
                "Tags_extracted": False,
                "processed": False
            }

            master_index_dict[nume_xml] = meta_fisier
            flag_updates_locala[nume_xml] = meta_fisier
            fisiere_noi_descarcate += 1
            print(f"✅ Descărcat și salvat cu succes în Drive: {nume_xml} (ID: {file_id})", flush=True)

        except Exception as e:
            print(f"❌ Eroare la încărcarea fișierului {nume_xml} pe Google Drive: {e}", flush=True)
        finally:
            if os.path.exists(cale_temp_xml):
                os.remove(cale_temp_xml)

        pagina += 1
        time.sleep(0.5)

    if flag_updates_locala:
        salveaza_micro_index(service, flag_updates_locala)

    print(f"📊 Summary Anul {an}: {fisiere_noi_descarcate} fișiere noi adăugate.", flush=True)


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
def main():
    service = get_drive_service()

    print("📥 Încărcare Master Index în memorie...", flush=True)
    if hasattr(XML_INDEX_READER, "descarca_index_master"):
        master_data = XML_INDEX_READER.descarca_index_master(service)
    else:
        master_data = XML_INDEX_READER.descarca_master_index(service)

    master_index_dict = master_data.get("fisiere", {})
    print(f"✅ Master Index încărcat cu succes! ({len(master_index_dict):,} fișiere unice protejate în memorie)", flush=True)

    an_start = 1948
    an_stop = 2026

    if len(sys.argv) >= 2:
        an_start = int(sys.argv[1])
    if len(sys.argv) >= 3:
        an_stop = int(sys.argv[2])

    print(f"🚀 Pornire proces descărcare pentru intervalul de ani: {an_start} - {an_stop}", flush=True)

    for an in range(an_start, an_stop + 1):
        proceseaza_an(service, master_index_dict, an)


if __name__ == "__main__":
    main()
