import os
import sys
import time
import json
import socket
import re
import traceback
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

from drive_config import (
    FOLDERE_XML_IDS,
    get_file_params,
)

# Revenire strictă la SUDS (Motorul SOAP oficial)
try:
    from suds.client import Client
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "suds-py3"], check=True)
    from suds.client import Client

# Preluarea creierului care gestionează indexul
try:
    import XML_INDEX_READER
except ImportError:
    from Scripts_XML import XML_INDEX_READER

# ==============================================================================
# CONFIGURARE CONSTANTE
# ==============================================================================
URL_HOST = "legislatie.just.ro"
URL_WSDL = f"http://{URL_HOST}/apiws/FreeWebService.svc?wsdl"
REZULTATE_PER_PAGINA = 10
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES")

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
        except Exception:
            sys.exit(1)
    print("❌ Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


# ==============================================================================
# CLIENT SOAP WSDL (Arhitectura originală suds-py3 + Traceback Excepții)
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
        return False

    def descarca_pagina(self, an, pagina):
        for incercare in range(3):
            try:
                # Creare model exact prin metoda WSDL
                search_model = self.client.factory.create('SearchModel')
                search_model.NumarPagina = pagina
                search_model.RezultatePagina = REZULTATE_PER_PAGINA
                search_model.SearchAn = an

                raspuns = self.client.service.Search(search_model, self.token)
                return str(raspuns)
            except Exception as e:
                eroare_text = str(e).lower()
                # Gestionare expirare token
                if any(k in eroare_text for k in ["token", "expired", "unauthorized"]):
                    print("🔄 Token expirat. Se solicită un token nou...", flush=True)
                    self.renoieste_token()
                else:
                    print(f"\n================ EXCEPȚIE SOAP (Încercarea {incercare+1}/3) ================", flush=True)
                    print(f"⚠️ Eroare la descărcarea paginii An={an}, Pagina={pagina}:", flush=True)
                    # PRINTĂM EXACT TRACEBACK-UL BRUT DE LA SUDS
                    traceback.print_exc()
                    print("==================================================================\n", flush=True)
                time.sleep(2)
        return None


# ==============================================================================
# HELPERS PENTRU GOOGLE DRIVE
# ==============================================================================
def obtine_folder_id_pentru_an(an):
    if an < 2000: return FOLDERE_XML_IDS[0]
    elif an < 2010: return FOLDERE_XML_IDS[1] if len(FOLDERE_XML_IDS) > 1 else FOLDERE_XML_IDS[0]
    elif an < 2020: return FOLDERE_XML_IDS[2] if len(FOLDERE_XML_IDS) > 2 else FOLDERE_XML_IDS[0]
    else: return FOLDERE_XML_IDS[3] if len(FOLDERE_XML_IDS) > 3 else FOLDERE_XML_IDS[0]


def salveaza_xml_in_drive(service, continut_xml, nume_fisier, folder_id):
    cale_temp = Path(nume_fisier)
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            f.write(continut_xml)

        media = MediaFileUpload(str(cale_temp), mimetype="text/xml")
        file_metadata = {"name": nume_fisier, "parents": [folder_id]}

        params = get_file_params(nume_fisier)
        params.pop("drive_id", None)
        params["body"] = file_metadata
        params["media_body"] = media

        res = service.files().create(**params).execute()
        file_id = res.get("id")
        
        if cale_temp.exists(): cale_temp.unlink()
        return file_id
    except Exception as e:
        print(f"❌ Eroare salvare {nume_fisier}: {e}", flush=True)
        if cale_temp.exists(): cale_temp.unlink()
        return None


def salveaza_micro_index(service, flag_updates):
    if not FOLDER_TEMP_INDEXES_ID:
        print("⚠️ Nu se salvează jurnalul: lipsește TEMPORARY_XML_INDEXES din mediu!", flush=True)
        return

    timestamp = int(time.time() * 1000)
    nume_temp = f"temp_index_{timestamp}.json"
    data = {"flag_updates": flag_updates}
    cale_temp = Path(nume_temp)
    
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        media = MediaFileUpload(str(cale_temp), mimetype="application/json")
        file_metadata = {"name": nume_temp, "parents": [FOLDER_TEMP_INDEXES_ID]}

        params = get_file_params(nume_temp)
        params.pop("drive_id", None)
        params["body"] = file_metadata
        params["media_body"] = media

        service.files().create(**params).execute()
        print(f"🧩 Temp Index salvat: {nume_temp} ({len(flag_updates)} fișiere noi)", flush=True)
        if cale_temp.exists(): cale_temp.unlink()
    except Exception as e:
        print(f"⚠️ Eroare la salvarea temp_index: {e}", flush=True)
        if cale_temp.exists(): cale_temp.unlink()


# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def main():
    print("============================================================", flush=True)
    print(f"🚀 PORNIRE DESCĂRCARE XML JUST.RO | INTERVAL ANI: {AN_START} - {AN_END}", flush=True)
    print("============================================================", flush=True)

    drive_service = get_drive_service()
    soap_client = JustRoSoapClient(URL_WSDL)

    # 1. OBȚINERE MEMORIE: Master Index + temp_index-uri -> XML_INDEX_READER
    fisiere_explicite = set()
    try:
        fisiere_map = XML_INDEX_READER.obtine_index_virtual(drive_service)
        if fisiere_map:
            # Protecție contra indexului imbricat (extrage doar numele fișierelor)
            if len(fisiere_map) == 1 and isinstance(list(fisiere_map.values())[0], dict):
                cheie_radacina = list(fisiere_map.keys())[0]
                fisiere_explicite = set(fisiere_map[cheie_radacina].keys())
            else:
                fisiere_explicite = set(fisiere_map.keys())
            
            print(f"✅ Găsite {len(fisiere_explicite)} fișiere descărcate anterior în indexul virtual.", flush=True)
    except Exception as e:
        print(f"⚠️ Eroare la obținerea Indexului Virtual: {e}", flush=True)

    micro_updates = {}
    fisiere_descarcate_sesiune = 0

    # 2. PARCURGERE ANI (Salt inteligent + Descărcare)
    for an in range(AN_START, AN_END + 1):
        folder_destinatie_id = obtine_folder_id_pentru_an(an)
        
        # Extragem paginile deja descărcate PENTRU ANUL CURENT
        pagini_an_curent = []
        pattern = re.compile(rf"brut_legislatie_{an}_pag(\d+)\.xml")
        
        for fisier in fisiere_explicite:
            match = pattern.match(fisier)
            if match:
                pagini_an_curent.append(int(match.group(1)))
                
        # Calculăm cu ce pagină să începem (ultima găsită + 1)
        pagina = max(pagini_an_curent) + 1 if pagini_an_curent else 1
        
        print(f"\n📅 Începere procesare An: {an}...", flush=True)
        if pagini_an_curent:
            print(f"⏩ Resume inteligent: S-au găsit {len(pagini_an_curent)} pagini existente. Se reia direct de la Pagina {pagina}.", flush=True)

        consecutive_skips = 0

        while True:
            nume_xml = f"brut_legislatie_{an}_pag{pagina}.xml"

            # 3. VERIFICARE ANTI-DUPLICARE (În caz că au mai rămas goluri/suprapuneri)
            if nume_xml in fisiere_explicite or nume_xml in micro_updates:
                consecutive_skips += 1
                pagina += 1
                if consecutive_skips > 25:
                    print(f"⏭️ FAST-FORWARD: 25 pagini existente. Anul {an} marcat complet!", flush=True)
                    break
                continue

            consecutive_skips = 0 
            
            print(f"📥 Descărcare Just.ro: An={an}, Pagina={pagina} -> {nume_xml}...", flush=True)
            continut_xml = soap_client.descarca_pagina(an, pagina)

            # Dacă eșuează din cauza WSDL (traceback printat mai sus)
            if continut_xml is None:
                print(f"❌ Descărcarea paginii {pagina} a eșuat repetat. Ne oprim aici pentru anul {an}.", flush=True)
                break

            # Dacă pur și simplu nu mai sunt rezultate de la just.ro pentru acest an
            if "Legi[] = None" in continut_xml or len(continut_xml.strip()) < 50:
                print(f"ℹ️ S-au terminat paginile pentru anul {an} la pagina {pagina - 1}.", flush=True)
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
                print(f"   ✅ Salvat cu succes! [ID: {file_id[:10]}...]", flush=True)

            if len(micro_updates) >= 20:
                salveaza_micro_index(drive_service, micro_updates)
                micro_updates = {}

            pagina += 1
            time.sleep(0.3)

    if micro_updates:
        salveaza_micro_index(drive_service, micro_updates)

    print("\n============================================================", flush=True)
    print(f"🏁 PROCES FINALIZAT PENTRU {AN_START}-{AN_END}! Descărcate: {fisiere_descarcate_sesiune}", flush=True)
    print("============================================================", flush=True)

if __name__ == "__main__":
    main()
