import os
import sys
import time
import json
import socket
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
from googleapiclient.http import MediaFileUpload

# Importăm DOAR funcțiile și folderele sigure. 
# NU importăm XML_STORAGE_INDEX de aici pentru a evita erorile fatale de import.
from drive_config import (
    FOLDERE_XML_IDS,
    FOLDER_TEMP_INDEXES_ID,
    get_file_params,
    get_list_params,
)

# Import/Instalare automată suds pentru comunicare SOAP WSDL
try:
    from suds.client import Client
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "suds-py3"], check=True)
    from suds.client import Client

try:
    import XML_INDEX_READER
except ImportError:
    from Scripts_XML import XML_INDEX_READER


# ==============================================================================
# CONFIGURARE CONSTANTE & ENDPOINT WSDL
# ==============================================================================
URL_HOST = "legislatie.just.ro"
URL_WSDL = f"http://{URL_HOST}/apiws/FreeWebService.svc?wsdl"
REZULTATE_PER_PAGINA = 10

# PRELUARE ANI DIN ARGUMENTELE LINIEI DE COMANDĂ
if len(sys.argv) >= 3:
    AN_START = int(sys.argv[1])
    AN_END = int(sys.argv[2])
elif len(sys.argv) == 2 and "-" in sys.argv[1]:
    pasi = sys.argv[1].split("-")
    AN_START = int(pasi[0])
    AN_END = int(pasi[1])
elif len(sys.argv) == 2 and sys.argv[1].isdigit():
    AN_START = int(sys.argv[1])
    AN_END = int(sys.argv[1])
else:
    AN_START = 1990
    AN_END = 2026


# ==============================================================================
# VERIFICARE DNS (DEBUG)
# ==============================================================================
def verifica_dns(host):
    print(f"🔍 Verificare DNS pentru {host}...", flush=True)
    try:
        ip = socket.gethostbyname(host)
        print(f"✅ DNS OK: {host} rezolvat la {ip}", flush=True)
    except Exception as e:
        print(f"❌ Eroare DNS pentru {host}: {e}", flush=True)

# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API
# ==============================================================================
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
# CLASĂ CLIENT JUST.RO SOAP (CU SUDS)
# ==============================================================================
class JustRoSoapClient:
    def __init__(self, wsdl_url):
        self.wsdl_url = wsdl_url
        print(f"🌐 Inițializare client SOAP WSDL: {self.wsdl_url}...", flush=True)

        for incercare in range(5):
            try:
                self.client = Client(self.wsdl_url)
                print("✅ WSDL încărcat cu succes!", flush=True)
                self.token = None
                self.renoieste_token()
                return
            except Exception as e:
                print(f"⚠️ Eroare încărcare WSDL ({incercare+1}/5): {e}", flush=True)
                time.sleep(10)

        raise RuntimeError("Nu s-a putut încărca WSDL după 5 încercări")

    def renoieste_token(self):
        print("🔑 Solicitare Token nou de la Just.ro...", flush=True)
        for incercare in range(3):
            try:
                self.token = self.client.service.GetToken()
                if self.token:
                    print(f"✅ Token obținut cu succes!", flush=True)
                    return True
            except Exception as e:
                print(f"⚠️ Eroare obținere token ({incercare+1}/3): {e}", flush=True)
                time.sleep(2)
        print("❌ Nu s-a putut obține token-ul după 3 încercări!", flush=True)
        return False

    def descarca_pagina(self, an, pagina):
        for incercare in range(3):
            try:
                search_model = self.client.factory.create('SearchModel')
                search_model.NumarPagina = pagina
                search_model.RezultatePagina = REZULTATE_PER_PAGINA
                search_model.SearchAn = an

                raspuns = self.client.service.Search(search_model, self.token)
                return str(raspuns)
            except Exception as e:
                if any(k in str(e).lower() for k in ["token", "expired", "unauthorized"]):
                    print("🔄 Token expirat. Se solicită un token nou...", flush=True)
                    self.renoieste_token()
                else:
                    print(f"⚠️ Eroare la descărcarea paginii An={an}, Pagina={pagina}: {e}", flush=True)
                time.sleep(2)
        return None


# ==============================================================================
# SELECTARE FOLDER DESTINAȚIE PE ANI
# ==============================================================================
def obtine_folder_id_pentru_an(an):
    if an < 2000:
        return FOLDERE_XML_IDS[0]
    elif an < 2010:
        return FOLDERE_XML_IDS[1] if len(FOLDERE_XML_IDS) > 1 else FOLDERE_XML_IDS[0]
    elif an < 2020:
        return FOLDERE_XML_IDS[2] if len(FOLDERE_XML_IDS) > 2 else FOLDERE_XML_IDS[0]
    else:
        return FOLDERE_XML_IDS[3] if len(FOLDERE_XML_IDS) > 3 else FOLDERE_XML_IDS[0]


# ==============================================================================
# SALVARE ÎN GOOGLE DRIVE & MICRO-INDEX
# ==============================================================================
def salveaza_xml_in_drive(service, continut_xml, nume_fisier, folder_id):
    cale_temp = Path(nume_fisier)
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            f.write(continut_xml)

        media = MediaFileUpload(str(cale_temp), mimetype="text/xml")
        file_metadata = {
            "name": nume_fisier,
            "parents": [folder_id]
        }

        params = get_file_params(nume_fisier)
        params.pop("drive_id", None)  # Eliminăm parametrul care cauzează eroarea la Google API
        params["body"] = file_metadata
        params["media_body"] = media

        res = service.files().create(**params).execute()
        file_id = res.get("id")

        if cale_temp.exists():
            cale_temp.unlink()

        return file_id
    except Exception as e:
        print(f"❌ Eroare la salvarea în Drive a fișierului {nume_fisier}: {e}", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()
        return None


def salveaza_micro_index(service, flag_updates):
    timestamp = int(time.time() * 1000)
    nume_temp = f"temp_index_{timestamp}.json"
    data = {"flag_updates": flag_updates}

    cale_temp = Path(nume_temp)
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        media = MediaFileUpload(str(cale_temp), mimetype="application/json")
        file_metadata = {
            "name": nume_temp,
            "parents": [FOLDER_TEMP_INDEXES_ID]
        }

        params = get_file_params(nume_temp)
        params.pop("drive_id", None)  # Eliminăm parametrul care cauzează eroarea la Google API
        params["body"] = file_metadata
        params["media_body"] = media

        service.files().create(**params).execute()
        print(f"🧩 Micro-index salvat în Drive: {nume_temp} ({len(flag_updates)} fișiere adăugate)", flush=True)

        if cale_temp.exists():
            cale_temp.unlink()
    except Exception as e:
        print(f"⚠️ Eroare la salvarea micro-index-ului: {e}", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()


# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def main():
    print("============================================================", flush=True)
    print(f"🚀 PORNIRE DESCĂRCARE XML JUST.RO | INTERVAL ANI: {AN_START} - {AN_END}", flush=True)
    print("============================================================", flush=True)

    verifica_dns(URL_HOST)

    drive_service = get_drive_service()
    soap_client = JustRoSoapClient(URL_WSDL)

    # 1. DESCĂRCARE DIRECTĂ A INDEXULUI MASTER (Filosofie zero hardcoding via API / Env)
    print("\n⚡ Construire Index Virtual LIVE...", flush=True)
    fisiere_explicite = set()
    nume_index_local = "index_xml.json.gz"
    
    # Preluăm variabila publică direct din mediul de rulare, dacă există
    id_index_drive = os.getenv("XML_STORAGE_INDEX")
    
    try:
        # Dacă nu o avem în variabile de mediu, o găsim dinamic după nume
        if not id_index_drive:
            print(f"🔍 Se caută '{nume_index_local}' pe Google Drive...", flush=True)
            rezultat_cautare = drive_service.files().list(
                q=f"name='{nume_index_local}' and trashed=false",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="files(id, name)"
            ).execute()
            fisiere_gasite = rezultat_cautare.get('files', [])
            if fisiere_gasite:
                id_index_drive = fisiere_gasite[0]['id']

        if id_index_drive:
            print(f"📥 Descărcare Master Index (ID: {id_index_drive})...", flush=True)
            request = drive_service.files().get_media(fileId=id_index_drive)
            
            with open(nume_index_local, "wb") as f:
                f.write(request.execute())
                
            fisiere_map = XML_INDEX_READER.incarc_index_master_gz(nume_index_local)
            if fisiere_map:
                fisiere_explicite = set(fisiere_map.keys())
            print(f"✅ Index Virtual generat cu succes! Total fișiere cunoscute: {len(fisiere_explicite):,}", flush=True)
        else:
            print(f"⚠️ Nu s-a găsit indexul pe Drive. Se începe cu un index gol.", flush=True)

    except Exception as e:
        print(f"⚠️ Eroare la descărcarea/citirea Index-ului Master: {e}. Se va continua cu index gol.", flush=True)

    micro_updates = {}
    fisiere_descarcate_sesiune = 0

    # 2. PARCURGERE ANI
    for an in range(AN_START, AN_END + 1):
        folder_destinatie_id = obtine_folder_id_pentru_an(an)
        pagina = 1
        consecutive_skips = 0
        pagini_sarite_an_curent = 0
        pagini_descarcate_an_curent = 0

        print(f"\n📅 Începere procesare An: {an}...", flush=True)

        while True:
            nume_xml = f"brut_legislatie_{an}_pag{pagina}.xml"

            if nume_xml in fisiere_explicite or nume_xml in micro_updates:
                consecutive_skips += 1
                pagini_sarite_an_curent += 1
                pagina += 1
                
                if consecutive_skips > 25:
                    print(f"⏭️ FAST-FORWARD: Găsite 25 pagini consecutive existente în Index. An marcat complet!", flush=True)
                    break
                continue

            consecutive_skips = 0 
            
            if pagini_sarite_an_curent > 0 and pagini_descarcate_an_curent == 0:
                print(f"⏩ Resume automat: S-a făcut Skip peste {pagini_sarite_an_curent} pagini existente. Se reia descărcarea de la Pagina {pagina}...", flush=True)

            print(f"📥 Descărcare Just.ro: An={an}, Pagina={pagina} -> {nume_xml}...", flush=True)
            continut_xml = soap_client.descarca_pagina(an, pagina)

            if not continut_xml or "Legi[] = None" in continut_xml or len(continut_xml.strip()) < 50:
                total_pagini_an = pagina - 1
                print(f"ℹ️ S-au terminat paginile pentru anul {an} la pagina {total_pagini_an} (Existente: {pagini_sarite_an_curent}, Descărcate Noi: {pagini_descarcate_an_curent}).", flush=True)
                break

            file_id = salveaza_xml_in_drive(drive_service, continut_xml, nume_xml, folder_destinatie_id)

            if file_id:
                micro_updates[nume_xml] = {
                    "id": file_id,
                    "folder_id": folder_destinatie_id,
                    "an": an,
                    "pagina": pagina,
                    "downloaded": True,
                    "processed": False
                }
                fisiere_descarcate_sesiune += 1
                pagini_descarcate_an_curent += 1
                print(f"   ✅ Salvat cu succes! [ID: {file_id[:10]}...]", flush=True)

            if len(micro_updates) >= 20:
                salveaza_micro_index(drive_service, micro_updates)
                micro_updates = {}

            pagina += 1
            time.sleep(0.3)

    if micro_updates:
        salveaza_micro_index(drive_service, micro_updates)

    print("\n============================================================", flush=True)
    print(f"🏁 PROCES FINALIZAT PENTRU {AN_START}-{AN_END}! Total fișiere noi descărcate: {fisiere_descarcate_sesiune:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
