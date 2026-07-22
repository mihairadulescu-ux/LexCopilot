import os
import sys
import time
import json
import re
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
URL_WSDL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"
REZULTATE_PER_PAGINA = 10
LIMITA_PAGINI_GOALE_CONSECUTIVE = 20  # Condiție de oprire a anului

# PRELUARE ANI DIN ARGUMENTELE LINIEI DE COMANDĂ (PENTRU GITHUB ACTIONS MATRIX)
if len(sys.argv) >= 3:
    AN_START = int(sys.argv[1])
    AN_END = int(sys.argv[2])
else:
    AN_START = 1990
    AN_END = 2026


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API
# ==============================================================================
def get_drive_service():
    """Autentificare în Google Drive API."""
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
# CLASĂ CLIENT JUST.RO SOAP
# ==============================================================================
class JustRoSoapClient:
    def __init__(self, wsdl_url):
        self.wsdl_url = wsdl_url
        print(f"🌐 Inițializare client SOAP WSDL: {self.wsdl_url}...", flush=True)
        self.client = Client(self.wsdl_url)
        self.token = None
        self.renoieste_token()

    def renoieste_token(self):
        """Preluare sau reîmprospătare token de sesiune."""
        print("🔑 Solicitare Token nou de la Just.ro...", flush=True)
        for incercare in range(3):
            try:
                self.token = self.client.service.GetToken()
                if self.token:
                    print(f"✅ Token obținut cu succes!", flush=True)
                    return True
            except Exception as e:
                print(f"⚠️ Eroare la obținerea token-ului (încercarea {incercare+1}/3): {e}", flush=True)
                time.sleep(2)
        print("❌ Nu s-a putut obține token-ul după 3 încercări!", flush=True)
        return False

    def descarca_pagina(self, an, pagina, max_retries=2):
        """Interogare pagină standard Just.ro."""
        for incercare in range(1, max_retries + 1):
            try:
                search_model = self.client.factory.create('SearchModel')
                search_model.NumarPagina = pagina
                search_model.RezultatePagina = REZULTATE_PER_PAGINA
                search_model.SearchAn = an

                raspuns = self.client.service.Search(search_model, self.token)
                
                # Verificare răspuns valid cu date reale (minim 50 caractere)
                if raspuns and "Legi[] = None" not in str(raspuns) and len(str(raspuns).strip()) >= 50:
                    return str(raspuns)
                else:
                    if incercare < max_retries:
                        time.sleep(1)
                        continue
                    return None

            except Exception as e:
                err_str = str(e).lower()
                if "token" in err_str or "expired" in err_str or "unauthorized" in err_str:
                    print("🔄 Token expirat. Se solicită un token nou...", flush=True)
                    self.renoieste_token()
                else:
                    if incercare < max_retries:
                        time.sleep(1.5)
                    else:
                        return None
        return None


# ==============================================================================
# SELECTARE FOLDER DESTINAȚIE PE ANI (SHARED DRIVES)
# ==============================================================================
def obtine_folder_id_pentru_an(an):
    """Returnează ID-ul de folder adecvat în funcție de an."""
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

        params = get_file_params()
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

        params = get_file_params()
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

    drive_service = get_drive_service()
    soap_client = JustRoSoapClient(URL_WSDL)

    # 1. GENERARE INDEX VIRTUAL LIVE (MASTER INDEX + MICRO-INDEKSI + DELTA DRIVE)
    print("\n⚡ Construire Index Virtual LIVE (Master Index + Micro-Indecși + Delta Drive)...", flush=True)
    fisiere_explicite = set()
    try:
        index_virtual = XML_INDEX_READER.obtine_index_virtual(drive_service)
        fisiere_map = index_virtual.get("fisiere", {})
        fisiere_explicite = set(fisiere_map.keys())
        print(f"✅ Index Virtual generat cu succes! Total fișiere cunoscute: {len(fisiere_explicite):,}", flush=True)
    except Exception as e:
        print(f"⚠️ Eroare la generarea Index-ului Virtual: {e}. Se va continua cu index gol.", flush=True)

    micro_updates = {}
    fisiere_descarcate_sesiune = 0

    # 2. Parcurgere ani
    for an in range(AN_START, AN_END + 1):
        folder_destinatie_id = obtine_folder_id_pentru_an(an)
        pagini_descarcate_an_curent = 0

        # Identificare pagini existente în index pentru anul curent
        pattern_an = re.compile(rf"^brut_legislatie_{an}_pag(\d+)\.xml$")
        set_pagini_existente = set()

        for nume_f in fisiere_explicite.union(micro_updates.keys()):
            match = pattern_an.match(nume_f)
            if match:
                set_pagini_existente.add(int(match.group(1)))

        # PASUL A: UMPLEREA GĂURILOR DIN SECVENȚĂ (GAP-FILLING)
        if set_pagini_existente:
            max_pag_existenta = max(set_pagini_existente)
            gauri = [p for p in range(1, max_pag_existenta) if p not in set_pagini_existente]

            print(f"\n📅 Anul {an}: Găsite {len(set_pagini_existente):,} pagini existente pe Drive (Ultima: pag{max_pag_existenta}).", flush=True)

            if gauri:
                print(f"🔎 [GAP-FILLING] Identificate {len(gauri)} găuri în secvență: {gauri[:10]}... Se descarcă paginile lipsă...", flush=True)
                for pag_gap in gauri:
                    nume_xml_gap = f"brut_legislatie_{an}_pag{pag_gap}.xml"
                    print(f"📥 [GAP] Descărcare Just.ro: An={an}, Pagina={pag_gap} -> {nume_xml_gap}...", flush=True)
                    
                    continut_gap = soap_client.descarca_pagina(an, pag_gap, max_retries=2)
                    if continut_gap:
                        file_id = salveaza_xml_in_drive(drive_service, continut_gap, nume_xml_gap, folder_destinatie_id)
                        if file_id:
                            micro_updates[nume_xml_gap] = {
                                "id": file_id,
                                "folder_id": folder_destinatie_id,
                                "an": an,
                                "pagina": pag_gap,
                                "downloaded": True,
                                "processed": False
                            }
                            fisiere_descarcate_sesiune += 1
                            pagini_descarcate_an_curent += 1
                            set_pagini_existente.add(pag_gap)
                            print(f"   ✅ [GAP REPARAT] Salvat cu succes! [ID: {file_id[:10]}...]", flush=True)
                    time.sleep(0.3)

            # După repararea găurilor, continuăm de la următoarea pagină după maximul existent
            pagina_start = max_pag_existenta + 1
            print(f"⏩ Se continuă descărcarea anului {an} de la Pagina {pagina_start}...", flush=True)
        else:
            pagina_start = 1
            print(f"\n📅 Anul {an}: Nicio pagină găsită în Index. Se pornește de la Pagina 1...", flush=True)

        # PASUL B: DESCĂRCARE CONTINUĂ DE LA PAGINA_START PÂNĂ LA LIMITA DE 20 PAGINI GOALE
        pagina = pagina_start
        pagini_goale_consecutive = 0

        while True:
            nume_xml = f"brut_legislatie_{an}_pag{pagina}.xml"

            # Double-check anti-duplicate
            if nume_xml in fisiere_explicite or nume_xml in micro_updates:
                pagina += 1
                pagini_goale_consecutive = 0
                continue

            print(f"📥 Descărcare Just.ro: An={an}, Pagina={pagina} -> {nume_xml}...", flush=True)
            continut_xml = soap_client.descarca_pagina(an, pagina, max_retries=2)

            if continut_xml:
                pagini_goale_consecutive = 0
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
            else:
                pagini_goale_consecutive += 1
                print(f"   ⚠️ Pagina {pagina} este GOLĂ/lipsă ({pagini_goale_consecutive}/{LIMITA_PAGINI_GOALE_CONSECUTIVE} consecutive)...", flush=True)

                if pagini_goale_consecutive >= LIMITA_PAGINI_GOALE_CONSECUTIVE:
                    total_pagini_valide = pagina - LIMITA_PAGINI_GOALE_CONSECUTIVE
                    print(f"\n🛑 S-a atins limita de {LIMITA_PAGINI_GOALE_CONSECUTIVE} pagini goale consecutive! Anul {an} este complet (Aproximativ {total_pagini_valide} pagini reale). Trecem la anul următor.\n", flush=True)
                    break

            pagina += 1
            time.sleep(0.3)

    if micro_updates:
        salveaza_micro_index(drive_service, micro_updates)

    print("\n============================================================", flush=True)
    print(f"🏁 PROCES FINALIZAT PENTRU {AN_START}-{AN_END}! Total fișiere noi descărcate: {fisiere_descarcate_sesiune:,}", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
