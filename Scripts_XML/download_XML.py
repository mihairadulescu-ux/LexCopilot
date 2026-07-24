import os
import sys
import json
import time
import tarfile
from pathlib import Path

# Stream live ne-bufferat pentru GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))

try:
    from suds.client import Client
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "suds-py3"], check=True)
    from suds.client import Client

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from drive_config import FOLDERE_XML_IDS, FOLDER_INDEX_ID, URL_WSDL

# Preluare An din linia de comandă (ex: python download_xml.py 1990)
AN_TARGET = int(sys.argv[1]) if len(sys.argv) >= 2 and sys.argv[1].isdigit() else 1990
REZULTATE_PER_PAGINA = 10

# Workspace local pe runner-ul de Linux
DIR_TEMP_LOCAL = Path(f"/tmp/xml_workspace_{AN_TARGET}")
DIR_TEMP_LOCAL.mkdir(parents=True, exist_ok=True)


def get_drive_service():
    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )
    if not creds_json:
        print("❌ [AUTH] Lipsă secret GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
        sys.exit(1)

    try:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        print(f"❌ [AUTH] Eroare Google Drive: {e}", flush=True)
        sys.exit(1)


# ==============================================================================
# CLIENT SOAP JUST.RO
# ==============================================================================
class JustRoSoapClient:
    def __init__(self, wsdl_url):
        if not wsdl_url:
            print("❌ [SOAP] Adresa WSDL nu este definită în mediu!", flush=True)
            sys.exit(1)
        self.wsdl_url = wsdl_url
        print("🌐 Inițializare client SOAP WSDL...", flush=True)
        self.client = Client(self.wsdl_url)
        self.token = None
        self.renoieste_token()

    def renoieste_token(self):
        print("🔑 Solicitare Token nou...", flush=True)
        for incercare in range(3):
            try:
                self.token = self.client.service.GetToken()
                if self.token:
                    print("✅ Token obținut cu succes!", flush=True)
                    return True
            except Exception as e:
                print(f"⚠️ Eroare obținere token ({incercare+1}/3): {e}", flush=True)
                time.sleep(2)
        print("❌ Nu s-a putut obține token-ul după 3 încercări!", flush=True)
        return False

    def descarca_pagina_cu_retry(self, an, pagina):
        max_retries = 4
        for incercare in range(1, max_retries + 1):
            try:
                search_model = self.client.factory.create('SearchModel')
                search_model.NumarPagina = pagina
                search_model.RezultatePagina = REZULTATE_PER_PAGINA
                search_model.SearchAn = an

                raspuns = self.client.service.Search(search_model, self.token)
                continut_str = str(raspuns)

                if not continut_str or "Legi[] = None" in continut_str or len(continut_str.strip()) < 50:
                    return False, None, 0

                return True, continut_str, len(continut_str.encode('utf-8'))

            except Exception as e:
                err_msg = str(e).lower()
                if "token" in err_msg or "expired" in err_msg or "unauthorized" in err_msg:
                    print("🔄 Token expirat. Reîmprospătare...", flush=True)
                    self.renoieste_token()
                else:
                    print(f"⚠️ Eroare descărcare An={an}, Pagina={pagina} (încercare {incercare}/{max_retries}): {e}", flush=True)
                    if incercare < max_retries:
                        time.sleep(2)
        
        return False, None, 0


# ==============================================================================
# AUTO-INITIALIZARE & GESTIONARE RESURSE DRIVE
# ==============================================================================
def initializeaza_sau_incarca_micro_index(service, an):
    """
    Caută micro-indexul pe Discul 0.
    Dacă NU există, îl inițializează automat și îl creează pe Drive.
    """
    nume_micro = f"index_an_{an}.json"
    try:
        q = f"'{FOLDER_INDEX_ID}' in parents and name = '{nume_micro}' and trashed=false"
        res = service.files().list(q=q, spaces='drive', fields="files(id)", supportsAllDrives=True).execute()
        files = res.get('files', [])

        if files:
            file_id = files[0]['id']
            req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
            continut = req.execute().decode('utf-8')
            if continut.strip() and continut.strip() != "{}":
                stare = json.loads(continut)
                print(f"   ℹ️ Micro-index existent încărcat de pe Discul 0 (ID: {file_id}).", flush=True)
                return file_id, stare
            else:
                print(f"   ℹ️ Micro-index existent este gol. Se va re-inițializa.", flush=True)
                file_id_existenta = file_id
        else:
            file_id_existenta = None

    except Exception as e:
        print(f"⚠️ Atenție la căutarea micro-indexului: {e}", flush=True)
        file_id_existenta = None

    # Inițializare structură nouă dacă nu s-a găsit sau era gol
    stare_noua = {
        "an": an,
        "status": "IN_PROGRES",
        "ultimul_update": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_xml_valid": 0,
        "drive_archive_file_id": None,
        "pagini_descarcate": {}
    }

    print(f"   🆕 Auto-inițializare Micro-Index nou pentru anul {an}...", flush=True)
    file_id = salveaza_micro_index(service, an, stare_noua, file_id_existenta)
    return file_id, stare_noua


def cauta_sau_initializeaza_arhiva(service, an, target_drive_id):
    """
    Verifică dacă există deja arhiva .tar.gz pe Drive-ul de stocare alocat.
    Returnează ID-ul dacă există sau None dacă va fi creată la prima sincronizare.
    """
    nume_tar = f"brut_XML_{an}.tar.gz"
    try:
        q = f"'{target_drive_id}' in parents and name = '{nume_tar}' and trashed=false"
        res = service.files().list(q=q, spaces='drive', fields="files(id)", supportsAllDrives=True).execute()
        files = res.get('files', [])
        if files:
            f_id = files[0]['id']
            print(f"   📦 Arhivă existentă găsită pe Drive (ID: {f_id}).", flush=True)
            return f_id
    except Exception as e:
        print(f"⚠️ Atenție la verificare arhivă: {e}", flush=True)

    print(f"   📦 Nicio arhivă găsită pentru anul {an}. Va fi creată automat pe Drive la primul sync.", flush=True)
    return None


def actualizeaza_sau_creeaza_tar(service, an, dir_xml_local, target_drive_id, archive_file_id_existenta=None):
    cale_tar_local = DIR_TEMP_LOCAL / f"brut_XML_{an}.tar.gz"
    print(f"\n📦 [SYNC TAR.GZ] Împachetare incrementală pentru anul {an}...", flush=True)

    with tarfile.open(cale_tar_local, "w:gz") as tar:
        for f_xml in dir_xml_local.glob("*.xml"):
            tar.add(f_xml, arcname=f_xml.name)

    marime_mb = cale_tar_local.stat().st_size / (1024 * 1024)
    media = MediaFileUpload(str(cale_tar_local), mimetype='application/gzip', resumable=True)

    if archive_file_id_existenta:
        print(f"   🔄 Actualizare arhivă pe Drive (ID: {archive_file_id_existenta}) | {marime_mb:.2f} MB...", flush=True)
        updated_file = service.files().update(
            fileId=archive_file_id_existenta,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        drive_id = updated_file.get('id')
    else:
        print(f"   ☁️ Inițializare și creare arhivă nouă pe Drive | {marime_mb:.2f} MB...", flush=True)
        file_metadata = {'name': f"brut_XML_{an}.tar.gz", 'parents': [target_drive_id]}
        created_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        drive_id = created_file.get('id')

    print(f"   ✅ Arhivă sincronizată cu succes! File ID: {drive_id}", flush=True)
    return drive_id


def salveaza_micro_index(service, an, stare_index, index_file_id=None):
    nume_micro = f"index_an_{an}.json"
    cale_json_local = DIR_TEMP_LOCAL / nume_micro

    with open(cale_json_local, "w", encoding="utf-8") as f:
        json.dump(stare_index, f, indent=2, ensure_ascii=False)

    media = MediaFileUpload(str(cale_json_local), mimetype='application/json')

    if index_file_id:
        service.files().update(
            fileId=index_file_id,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        ret_id = index_file_id
    else:
        file_metadata = {'name': nume_micro, 'parents': [FOLDER_INDEX_ID]}
        res = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        ret_id = res.get('id')

    cale_json_local.unlink(missing_ok=True)
    return ret_id


# ==============================================================================
# ENGINE PRINCIPAL PER AN
# ==============================================================================
def proceseaza_an_fir_independent(an):
    drive_service = get_drive_service()
    soap_client = JustRoSoapClient(URL_WSDL)

    if not FOLDERE_XML_IDS:
        print("❌ [CONFIG] FOLDERE_XML_IDS este gol!", flush=True)
        sys.exit(1)

    idx_disc = (an % len(FOLDERE_XML_IDS))
    target_drive_id = FOLDERE_XML_IDS[idx_disc]

    dir_xml_local = DIR_TEMP_LOCAL / "xml_files"
    dir_xml_local.mkdir(parents=True, exist_ok=True)

    print("============================================================", flush=True)
    print(f"🚀 START PROCESARE SOAP PENTRU ANUL {an}", flush=True)
    print(f"📂 Drive Destinație: Shared Drive #{idx_disc + 1} (ID: {target_drive_id})", flush=True)
    print("============================================================", flush=True)

    # 1. AUTO-INITIALIZARE SAU ÎNCĂRCARE MICRO-INDEX
    index_file_id, stare_index = initializeaza_sau_incarca_micro_index(drive_service, an)
    
    # 2. AUTO-INITIALIZARE SAU CĂUTARE ARHIVĂ EXISTENTĂ
    archive_file_id = stare_index.get("drive_archive_file_id")
    if not archive_file_id:
        archive_file_id = cauta_sau_initializeaza_arhiva(drive_service, an, target_drive_id)

    pagini_descarcate = stare_index.get("pagini_descarcate", {})

    numarator_consecutive_goale = 0
    pagini_de_la_ultimul_sync = 0
    pagina_curenta = 1

    while True:
        pagina_str = str(pagina_curenta)

        # Skip pagini deja descărcate cu succes (Reluare inteligentă)
        if pagini_descarcate.get(pagina_str) == "OK":
            pagina_curenta += 1
            numarator_consecutive_goale = 0
            continue

        is_ok, continut_xml, marime_bytes = soap_client.descarca_pagina_cu_retry(an, pagina_curenta)

        if is_ok:
            nume_xml = f"brut_XML_{an}_pag{pagina_curenta}.xml"
            with open(dir_xml_local / nume_xml, "w", encoding="utf-8") as f:
                f.write(continut_xml)

            pagini_descarcate[pagina_str] = "OK"
            numarator_consecutive_goale = 0
            pagini_de_la_ultimul_sync += 1

            print(f"   🟢 [AN {an} | PAGINA {pagina_curenta}] SOAP XML Valid | Dimensiune: {marime_bytes:,} bytes", flush=True)
        else:
            pagini_descarcate[pagina_str] = "GOL"
            numarator_consecutive_goale += 1
            print(f"   ⚪ [AN {an} | PAGINA {pagina_curenta}] Răspuns GOL | Consecutiv goale: {numarator_consecutive_goale}/20", flush=True)

        # Salvare incrementală la fiecare 200 de pagini noi
        if pagini_de_la_ultimul_sync >= 200:
            archive_file_id = actualizeaza_sau_creeaza_tar(drive_service, an, dir_xml_local, target_drive_id, archive_file_id)
            
            stare_index.update({
                "an": an,
                "status": "IN_PROGRES",
                "ultimul_update": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_xml_valid": sum(1 for v in pagini_descarcate.values() if v == "OK"),
                "drive_archive_file_id": archive_file_id,
                "pagini_descarcate": pagini_descarcate
            })
            index_file_id = salveaza_micro_index(drive_service, an, stare_index, index_file_id)
            pagini_de_la_ultimul_sync = 0

        # Punct de oprire: 20 de pagini goale consecutive
        if numarator_consecutive_goale >= 20:
            print(f"\n🛑 [STOP AN {an}] 20 de pagini goale consecutive. Anul {an} este complet!", flush=True)
            break

        pagina_curenta += 1
        time.sleep(0.2)

    # Sincronizare finală la terminarea anului
    if pagini_de_la_ultimul_sync > 0 or not archive_file_id:
        archive_file_id = actualizeaza_sau_creeaza_tar(drive_service, an, dir_xml_local, target_drive_id, archive_file_id)

    stare_index.update({
        "an": an,
        "status": "FINALIZAT",
        "ultimul_update": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_xml_valid": sum(1 for v in pagini_descarcate.values() if v == 'OK'),
        "drive_archive_file_id": archive_file_id,
        "pagini_descarcate": pagini_descarcate
    })
    salveaza_micro_index(drive_service, an, stare_index, index_file_id)

    print("\n============================================================", flush=True)
    print(f"🏁 PROCESARE FINALIZATĂ CU SUCCES PENTRU ANUL {an}!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    proceseaza_an_fir_independent(AN_TARGET)
