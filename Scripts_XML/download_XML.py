import os
import sys
import time
import json
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

# Motor SOAP SUDS
try:
    from suds.client import Client
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "suds-py3"], check=True)
    from suds.client import Client

# Import modul citire index
try:
    import XML_INDEX_READER
except ImportError:
    from Scripts_XML import XML_INDEX_READER

# ==============================================================================
# CONFIGURARE CONSTANTE & PRELUARE STRICTĂ DIN MEDIU (FĂRĂ FALLBACK-URI)
# ==============================================================================
URL_HOST = "legislatie.just.ro"
URL_WSDL = f"http://{URL_HOST}/apiws/FreeWebService.svc?wsdl"
REZULTATE_PER_PAGINA = 10

# Preluare STRICTĂ din mediul de execuție
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES")
XML_STORAGE_INDEX_ID = os.getenv("XML_STORAGE_INDEX")

# Verificare de siguranță la pornire
if not FOLDER_TEMP_INDEXES_ID or not XML_STORAGE_INDEX_ID:
    print("🛑 EROARE CRITICĂ: Variabilele 'TEMPORARY_XML_INDEXES' sau 'XML_STORAGE_INDEX' nu sunt definite în mediu!", flush=True)
    sys.exit(1)

# PRELUARE ANI DIN ARGUMENTELE LINIEI DE COMANDĂ
if len(sys.argv) >= 3:
    AN_START, AN_END = int(sys.argv[1]), int(sys.argv[2])
elif len(sys.argv) == 2 and "-" in sys.argv[1]:
    pasi = sys.argv[1].split("-")
    AN_START, AN_END = int(pasi[0]), int(pasi[1])
elif len(sys.argv) == 2 and sys.argv[1].isdigit():
    AN_START = AN_END = int(sys.argv[1])
else:
    AN_START, AN_END = 1990, 2026


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
            print(f"❌ Eroare la parsarea JSON-ului Service Account: {e}", flush=True)
            sys.exit(1)
            
    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare la citirea service_account.json local: {e}", flush=True)

    print("❌ Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


# ==============================================================================
# CLIENT SOAP WSDL (SUDS)
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
                search_model = self.client.factory.create('SearchModel')
                search_model.NumarPagina = pagina
                search_model.RezultatePagina = REZULTATE_PER_PAGINA
                search_model.SearchAn = an
                raspuns = self.client.service.Search(search_model, self.token)
                return str(raspuns)
            except Exception as e:
                eroare_text = str(e).lower()
                if any(k in eroare_text for k in ["token", "expired", "unauthorized"]):
                    print("🔄 Token expirat. Se solicită un token nou...", flush=True)
                    self.renoieste_token()
                else:
                    print(f"\n================ EXCEPȚIE SOAP (Încercarea {incercare+1}/3) ================", flush=True)
                    print(f"⚠️ Eroare la descărcarea paginii An={an}, Pagina={pagina}:", flush=True)
                    traceback.print_exc()
                    print("==================================================================\n", flush=True)
                time.sleep(2)
        return None


# ==============================================================================
# HELPERS DRIVE & STOCARE
# ==============================================================================
def obtine_folder_id_pentru_an(an):
    if an < 2000: return FOLDERE_XML_IDS[0]
    elif an < 2010: return FOLDERE_XML_IDS[1] if len(FOLDERE_XML_IDS) > 1 else FOLDERE_XML_IDS[0]
    elif an < 2020: return FOLDERE_XML_IDS[2] if len(FOLDERE_XML_IDS) > 2 else FOLDERE_XML_IDS[0]
    else: return FOLDERE_XML_IDS[3] if len(FOLDERE_XML_IDS) > 3 else FOLDERE_XML_IDS[0]


def Curata_parametri_google(params):
    """Elimină toți parametrii interni/custom care nu sunt acceptați de API-ul Google Drive."""
    chei_custom = ["drive_id", "tip_stocare", "arhiva", "cale_interna", "an", "pagina"]
    for k in chei_custom:
        params.pop(k, None)
    return params


def salveaza_xml_in_drive(service, continut_xml, nume_fisier, folder_id):
    cale_temp = Path(nume_fisier)
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            f.write(continut_xml)

        media = MediaFileUpload(str(cale_temp), mimetype="text/xml")
        file_metadata = {"name": nume_fisier, "parents": [folder_id]}

        params = get_file_params(nume_fisier)
        params = Curata_parametri_google(params)
        params["body"] = file_metadata
        params["media_body"] = media

        res = service.files().create(**params).execute()
        file_id = res.get("id")
        
        if cale_temp.exists(): 
            cale_temp.unlink()
        return file_id
    except Exception as e:
        print(f"❌ Eroare salvare {nume_fisier}: {e}", flush=True)
        if cale_temp.exists(): 
            cale_temp.unlink()
        return None


def salveaza_micro_index(service, flag_updates):
    """Salvează micro-indexul respectând schema completă Master Index."""
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
        params = Curata_parametri_google(params)
        params["body"] = file_metadata
        params["media_body"] = media

        service.files().create(**params).execute()
        print(f"🧩 Temp Index salvat: {nume_temp} ({len(flag_updates)} fișiere noi)", flush=True)
        if cale_temp.exists(): 
            cale_temp.unlink()
    except Exception as e:
        print(f"⚠️ Eroare la salvarea temp_index: {e}", flush=True)
        if cale_temp.exists(): 
            cale_temp.unlink()


# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def main():
    print("============================================================", flush=True)
    print(f"🚀 PORNIRE DESCĂRCARE XML JUST.RO | INTERVAL ANI: {AN_START} - {AN_END}", flush=True)
    print("============================================================", flush=True)

    drive_service = get_drive_service()
    soap_client = JustRoSoapClient(URL_WSDL)

    # 1. ÎNCĂRCARE INDEX VIRTUAL LIVE
    fisiere_explicite = set()
    fisiere_map = {}
    try:
        fisiere_map = XML_INDEX_READER.obtine_index_virtual(drive_service)
        if fisiere_map:
            if len(fisiere_map) == 1 and isinstance(list(fisiere_map.values())[0], dict):
                cheie_radacina = list(fisiere_map.keys())[0]
                fisiere_explicite = set(fisiere_map[cheie_radacina].keys())
            else:
                fisiere_explicite = set(fisiere_map.keys())
            print(f"✅ Index Virtual Încărcat! Găsite {len(fisiere_explicite):,} fișiere totale în index.", flush=True)
    except Exception as e:
        print(f"⚠️ Eroare la obținerea Indexului Virtual: {e}", flush=True)

    micro_updates = {}
    fisiere_descarcate_sesiune = 0

    # 2. PARCURGERE ANI
    for an in range(AN_START, AN_END + 1):
        folder_destinatie_id = obtine_folder_id_pentru_an(an)
        pagini_an_curent = []
        
        # Filtrare STRICTĂ pe anul curent (suportă ambele tipuri de denumiri vechi/noi)
        pattern = re.compile(rf"brut_(?:XML|legislatie)_{an}_pag(\d+)\.xml", re.IGNORECASE)
        
        for fisier in fisiere_explicite:
            match = pattern.match(fisier)
            if match:
                pagini_an_curent.append(int(match.group(1)))
                
        # Calculare pagină de pornire (Resume inteligent)
        pagina_max_existenta = max(pagini_an_curent) if pagini_an_curent else 0
        pagina = pagina_max_existenta + 1
        
        print(f"\n📅 Procesare An: {an} | Fișiere găsite în index pt. acest an: {len(pagini_an_curent)} | Ultima pagină: {pagina_max_existenta}", flush=True)
        if pagina_max_existenta > 0:
            print(f"⏩ Reluare descărcare direct de la Pagina {pagina}...", flush=True)

        consecutive_skips = 0

        while True:
            # DENUMIREA OFICIALĂ A FIȘIERULUI
            nume_xml = f"brut_XML_{an}_pag{pagina}.xml"

            if nume_xml in fisiere_explicite or nume_xml in micro_updates:
                consecutive_skips += 1
                pagina += 1
                if consecutive_skips > 25:
                    print(f"⏭️ FAST-FORWARD: 25 pagini existente consecutive. Anul {an} marcat complet!", flush=True)
                    break
                continue

            consecutive_skips = 0 
            print(f"📥 Descărcare Just.ro: An={an}, Pagina={pagina} -> {nume_xml}...", flush=True)
            continut_xml = soap_client.descarca_pagina(an, pagina)

            if continut_xml is None:
                print(f"❌ Descărcarea paginii {pagina} a eșuat repetat (eroare rețea/WSDL). Oprire pe anul {an}.", flush=True)
                break

            # VERIFICARE RIGUROASĂ A SFÂRȘITULUI DE AN
            raspuns_text = str(continut_xml)
            if "Legi = None" in raspuns_text or "Legi[] = None" in raspuns_text or (len(raspuns_text.strip()) < 100 and "SearchResult" not in raspuns_text):
                print(f"ℹ️ Serverul Just.ro a confirmat finalul anului {an} la pagina {pagina - 1}.", flush=True)
                break

            file_id = salveaza_xml_in_drive(drive_service, continut_xml, nume_xml, folder_destinatie_id)

            if file_id:
                # Schema hibridă compatibilă cu Master Index
                micro_updates[nume_xml] = {
                    "an": int(an),
                    "pagina": int(pagina),
                    "tip_stocare": "individual",
                    "arhiva": None,
                    "cale_interna": None,
                    "drive_id": file_id
                }
                fisiere_descarcate_sesiune += 1
                print(f"   ✅ Salvat pe Drive! [ID: {file_id[:10]}...]", flush=True)

            if len(micro_updates) >= 20:
                salveaza_micro_index(drive_service, micro_updates)
                micro_updates = {}

            pagina += 1
            time.sleep(0.3)

    if micro_updates:
        salveaza_micro_index(drive_service, micro_updates)

    print("\n============================================================", flush=True)
    print(f"🏁 PROCES FINALIZAT PENTRU {AN_START}-{AN_END}! Total descărcate: {fisiere_descarcate_sesiune}", flush=True)
    print("============================================================", flush=True)

if __name__ == "__main__":
    main()
