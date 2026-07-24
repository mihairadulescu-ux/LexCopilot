import os
import sys
import json
import time
import tarfile
import tempfile
import io
import shutil
from pathlib import Path
import requests
from suds.client import Client

# Stream direct live fără buffer pentru GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from drive_config import (
    FOLDERE_XML_IDS,
    FOLDER_INDEX_ID,
    get_file_params,
    get_list_params
)

# Parametri de configurare
PRAG_SYNC_PAGINI = 50             # Sincronizare pe Drive la 50 de pagini noi
REZULTATE_PER_PAGINA = 10
MAX_RETRY_PAGINA = 3              # Reîncercări per pagină dacă dă 0 bytes
PAUZA_RETRY_SECUNDE = 5           # Pauză între reîncercări
MAX_PAGINI_GOALE_CONSECUTIVE = 20  # Oprește sesiunea dacă întâlnește 20 de pagini goale la rând


def get_drive_service():
    """Autentificare în Google Drive API prin Service Account JSON."""
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
        print(f"❌ [AUTH] Eroare Google Drive API: {e}", flush=True)
        sys.exit(1)


def primeste_token_soap(wsdl_url):
    """Solicită un token nou de autentificare de la serviciul SOAP Just.ro."""
    try:
        client = Client(wsdl_url)
        token = client.service.GetToken()
        return token
    except Exception as e:
        print(f"❌ Eroare la obținerea token-ului SOAP: {e}", flush=True)
        return None


def cauta_fisiere_pe_drive(service, parent_id, nume_fisier):
    """Caută un fișier după nume într-un folder specific pe Google Drive."""
    try:
        q = f"'{parent_id}' in parents and name = '{nume_fisier}' and trashed = false"
        params = get_list_params()
        params["q"] = q
        params["fields"] = "files(id, name)"
        res = service.files().list(**params).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None
    except Exception as e:
        print(f"⚠️ Eroare la căutarea fișierului '{nume_fisier}': {e}", flush=True)
        return None


def incarca_micro_index(service, an):
    """Încarcă fișierul index_an_YYYY.json de pe Discul 0 (Folder Index)."""
    nume_index = f"index_an_{an}.json"
    file_id = cauta_fisiere_pe_drive(service, FOLDER_INDEX_ID, nume_index)

    if not file_id:
        return None, {
            "an": str(an),
            "status": "IN_PROGRES",
            "drive_archive_file_id": "",
            "ultimul_update": "",
            "total_xml_valid": 0,
            "pagini_descarcate": {}
        }

    try:
        req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        content = req.execute().decode('utf-8')
        data = json.loads(content)
        return file_id, data
    except Exception as e:
        print(f"⚠️ Eroare la citirea micro-indexului {nume_index}: {e}", flush=True)
        return file_id, {
            "an": str(an),
            "status": "IN_PROGRES",
            "drive_archive_file_id": "",
            "ultimul_update": "",
            "total_xml_valid": 0,
            "pagini_descarcate": {}
        }


def salveaza_micro_index(service, file_id, index_data):
    """Salvează/Actualizează micro-indexul pe Discul 0."""
    an = index_data.get("an")
    nume_index = f"index_an_{an}.json"
    json_bytes = json.dumps(index_data, indent=2, ensure_ascii=False).encode('utf-8')

    media = MediaIoBaseUpload(io.BytesIO(json_bytes), mimetype='application/json')

    if file_id:
        params = get_file_params()
        params["fileId"] = file_id
        params["media_body"] = media
        service.files().update(**params).execute()
    else:
        file_metadata = {
            "name": nume_index,
            "parents": [FOLDER_INDEX_ID]
        }
        params = get_file_params()
        params["body"] = file_metadata
        params["media_body"] = media
        res = service.files().create(**params).execute()
        file_id = res.get("id")

    print(f"   💾 Micro-index '{nume_index}' salvat/actualizat cu succes pe Discul 0!", flush=True)
    return file_id


def descarca_si_sincronizeaza(an_target):
    """Procesul principal de descărcare SOAP cu raportare la final."""
    timp_start = time.time()
    wsdl_url = os.getenv("JUST_RO_WSDL_URL") or "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"
    service = get_drive_service()

    nume_drives = [d for d in FOLDERE_XML_IDS if d]
    drive_idx = int(an_target) % len(nume_drives) if nume_drives else 0
    shared_drive_id = FOLDERE_XML_IDS[drive_idx]

    print("🌐 Inițializare client SOAP WSDL...", flush=True)
    print("🔑 Solicitare Token nou...", flush=True)
    token = primeste_token_soap(wsdl_url)
    if not token:
        print("❌ Nu s-a putut obține token-ul SOAP!", flush=True)
        sys.exit(1)
    print("✅ Token obținut cu succes!", flush=True)

    print("============================================================", flush=True)
    print(f"🚀 START PROCESARE SOAP PENTRU ANUL {an_target}", flush=True)
    print(f"📂 Drive Destinație: Shared Drive #{drive_idx + 1} (ID: {shared_drive_id})", flush=True)
    print("============================================================", flush=True)

    micro_index_id, micro_data = incarca_micro_index(service, an_target)
    pagini_ok = micro_data.get("pagini_descarcate", {})

    nume_arhiva = f"brut_XML_{an_target}.tar.gz"
    archive_file_id = micro_data.get("drive_archive_file_id") or cauta_fisiere_pe_drive(service, shared_drive_id, nume_arhiva)

    if archive_file_id:
        micro_data["drive_archive_file_id"] = archive_file_id

    pagini_deja_procesate = [p for p, status in pagini_ok.items() if status == "OK"]
    if pagini_deja_procesate:
        print(f"🔄 RELUARE DETECTATĂ: Paginile 1..{len(pagini_deja_procesate)} sunt deja descărcate și validate pe Drive.", flush=True)

    dir_temp = tempfile.mkdtemp()
    folder_xmls = Path(dir_temp) / "xml_files"
    folder_xmls.mkdir(parents=True, exist_ok=True)
    cale_arhiva_local = Path(dir_temp) / nume_arhiva

    if archive_file_id:
        try:
            print(f"📥 Descărcare și extragere arhivă existentă de pe Drive pe runner...", flush=True)
            req = service.files().get_media(fileId=archive_file_id, supportsAllDrives=True)
            with open(cale_arhiva_local, "wb") as f:
                f.write(req.execute())

            with tarfile.open(cale_arhiva_local, "r:gz") as tar:
                tar.extractall(path=folder_xmls)
            
            cale_arhiva_local.unlink(missing_ok=True)
            print("✅ Arhivă extrasă local cu succes!", flush=True)
        except Exception as e:
            print(f"⚠️ Arhiva existentă nu a putut fi extrasă ({e}). Se va genera una nouă.", flush=True)

    pagina = 1
    fisiere_noi_in_pachet = 0
    pagini_goale_consecutive = 0
    
    # Statistici pentru raport
    pagini_noi_descarcate_sesiune = 0
    total_erori_sesiune = 0

    while True:
        str_pag = str(pagina)

        # Sare peste paginile validate anterior
        if pagini_ok.get(str_pag) == "OK":
            pagina += 1
            continue

        pagina_descarcata_cu_succes = False

        for incercare in range(1, MAX_RETRY_PAGINA + 1):
            soap_request = f"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:ns0="http://schemas.datacontract.org/2004/07/FreeWebService" xmlns:ns1="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns2="http://tempuri.org/">
   <SOAP-ENV:Header/>
   <ns1:Body>
      <ns2:Search>
         <ns2:SearchModel>
            <ns0:NumarPagina>{pagina}</ns0:NumarPagina>
            <ns0:RezultatePagina>{REZULTATE_PER_PAGINA}</ns0:RezultatePagina>
            <ns0:SearchAn>{an_target}</ns0:SearchAn>
         </ns2:SearchModel>
         <ns2:tokenKey>{token}</ns2:tokenKey>
      </ns2:Search>
   </ns1:Body>
</SOAP-ENV:Envelope>"""

            headers = {
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "http://tempuri.org/IFreeWebService/Search"
            }

            try:
                resp = requests.post("http://legislatie.just.ro/apiws/FreeWebService.svc", data=soap_request, headers=headers, timeout=30)
                continut_raw = resp.text.strip()
                dimensiune_bytes = len(resp.content)

                if "token" in continut_raw.lower() and ("expirat" in continut_raw.lower() or "invalid" in continut_raw.lower()):
                    print("🔄 Token expirat. Reîmprospătare...", flush=True)
                    token = primeste_token_soap(wsdl_url)
                    continue

                if dimensiune_bytes == 0 or "<" not in continut_raw or "Envelope>" not in continut_raw:
                    print(f"⚠️ [AN {an_target} | PAGINA {pagina}] Răspuns invalid/0 bytes ({incercare}/{MAX_RETRY_PAGINA}). Reîncercare în {PAUZA_RETRY_SECUNDE}s...", flush=True)
                    total_erori_sesiune += 1
                    time.sleep(PAUZA_RETRY_SECUNDE)
                    continue

                # Salvare fișier XML valid local
                nume_xml = f"brut_XML_{an_target}_pag{pagina}.xml"
                cale_xml = folder_xmls / nume_xml
                with open(cale_xml, "w", encoding="utf-8") as f:
                    f.write(resp.text)

                pagini_ok[str_pag] = "OK"
                fisiere_noi_in_pachet += 1
                pagini_noi_descarcate_sesiune += 1
                pagina_descarcata_cu_succes = True
                pagini_goale_consecutive = 0
                print(f"   🟢 [AN {an_target} | PAGINA {pagina}] SOAP XML Valid | Dimensiune: {dimensiune_bytes:,} bytes", flush=True)
                break

            except Exception as e:
                total_erori_sesiune += 1
                print(f"⚠️ [AN {an_target} | PAGINA {pagina}] Eroare rețea ({e}). Încercarea {incercare}/{MAX_RETRY_PAGINA}. Reîncercare în {PAUZA_RETRY_SECUNDE}s...", flush=True)
                time.sleep(PAUZA_RETRY_SECUNDE)

        if not pagina_descarcata_cu_succes:
            pagini_goale_consecutive += 1
            print(f"⚠️ [AN {an_target} | PAGINA {pagina}] Pagină fără date. Contor pagini goale: {pagini_goale_consecutive}/{MAX_PAGINI_GOALE_CONSECUTIVE}", flush=True)

        # Oprire sesiune curentă la 20 de pagini goale consecutive
        if pagini_goale_consecutive >= MAX_PAGINI_GOALE_CONSECUTIVE:
            print(f"\n✋ [AN {an_target}] S-au înregistrat {MAX_PAGINI_GOALE_CONSECUTIVE} pagini goale consecutive.", flush=True)
            print(f"🛑 Oprire sesiune curentă. Se salvează starea și se finalizează scriptul.", flush=True)
            break

        # Sincronizare intermediară pe Drive la 50 de pagini noi
        if fisiere_noi_in_pachet >= PRAG_SYNC_PAGINI:
            print(f"\n📦 [SYNC TAR.GZ & INDEX] Împachetare incrementală (50 de pagini noi)...", flush=True)
            
            with tarfile.open(cale_arhiva_local, "w:gz") as tar:
                for f in folder_xmls.glob("*.xml"):
                    tar.add(f, arcname=f.name)
            
            marime_mb = cale_arhiva_local.stat().st_size / (1024 * 1024)
            media = MediaFileUpload(str(cale_arhiva_local), mimetype="application/gzip", resumable=True)

            if archive_file_id:
                params = get_file_params()
                params["fileId"] = archive_file_id
                params["media_body"] = media
                service.files().update(**params).execute()
            else:
                file_metadata = {"name": nume_arhiva, "parents": [shared_drive_id]}
                params = get_file_params()
                params["body"] = file_metadata
                params["media_body"] = media
                res = service.files().create(**params).execute()
                archive_file_id = res.get("id")
                micro_data["drive_archive_file_id"] = archive_file_id

            print(f"   ☁️ Arhivă '{nume_arhiva}' ({marime_mb:.2f} MB) sincronizată pe Drive!", flush=True)

            micro_data["pagini_descarcate"] = pagini_ok
            micro_data["total_xml_valid"] = len(pagini_ok)
            micro_data["ultimul_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
            micro_index_id = salveaza_micro_index(service, micro_index_id, micro_data)

            cale_arhiva_local.unlink(missing_ok=True)
            fisiere_noi_in_pachet = 0

        pagina += 1

    # Sincronizare finală
    marime_finala_mb = 0.0
    if any(folder_xmls.iterdir()):
        print(f"\n🏁 [SYNC FINAL] Salvare finală arhivă și micro-index...", flush=True)
        
        with tarfile.open(cale_arhiva_local, "w:gz") as tar:
            for f in folder_xmls.glob("*.xml"):
                tar.add(f, arcname=f.name)
        
        marime_finala_mb = cale_arhiva_local.stat().st_size / (1024 * 1024)
        media = MediaFileUpload(str(cale_arhiva_local), mimetype="application/gzip", resumable=True)

        if archive_file_id:
            params = get_file_params()
            params["fileId"] = archive_file_id
            params["media_body"] = media
            service.files().update(**params).execute()
        else:
            file_metadata = {"name": nume_arhiva, "parents": [shared_drive_id]}
            params = get_file_params()
            params["body"] = file_metadata
            params["media_body"] = media
            res = service.files().create(**params).execute()
            archive_file_id = res.get("id")
            micro_data["drive_archive_file_id"] = archive_file_id

        micro_data["pagini_descarcate"] = pagini_ok
        micro_data["total_xml_valid"] = len(pagini_ok)
        micro_data["ultimul_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        salveaza_micro_index(service, micro_index_id, micro_data)

    shutil.rmtree(dir_temp, ignore_errors=True)

    # Calculare Raport de Sesiune
    durata_secunde = time.time() - timp_start
    viteza_pagini_pe_sec = pagini_noi_descarcate_sesiune / durata_secunde if durata_secunde > 0 else 0

    print("\n" + "=" * 60, flush=True)
    print(f"📊 RAPORT SESIUNE DESCĂRCARE — ANUL {an_target}", flush=True)
    print("=" * 60, flush=True)
    print(f"⏱️  Durată sesiune:               {durata_secunde / 60:.2f} minute ({durata_secunde:.1f}s)", flush=True)
    print(f"🟢 Pagini noi salvate acum:       {pagini_noi_descarcate_sesiune} pagini", flush=True)
    print(f"📦 Total pagini validate pe Drive: {len(pagini_ok)} pagini", flush=True)
    print(f"⚠️  Erori / Reîncercări rețea:     {total_erori_sesiune}", flush=True)
    print(f"⚡ Vitează medie:                 {viteza_pagini_pe_sec:.2f} pagini/secundă", flush=True)
    print(f"💾 Dimensiune arhivă Drive:        {marime_finala_mb:.2f} MB", flush=True)
    print("=" * 60 + "\n", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Specificați anul ca argument (ex: python download_XML.py 1990)", flush=True)
        sys.exit(1)

    an_input = sys.argv[1]
    descarca_si_sincronizeaza(an_input)
