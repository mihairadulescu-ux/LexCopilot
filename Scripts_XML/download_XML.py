import os
import sys
import argparse
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

# Evacuare live din buffer pentru afișare instantanee în GitHub Actions
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def print_live(msg):
    """Afișează mesajul și forțează evacuarea instantanee din buffer."""
    print(msg, flush=True)
    sys.stdout.flush()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from drive_config import FOLDERE_XML_IDS, FOLDER_TEMP_INDEXES_ID, get_file_params, get_list_params
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# Endpoint-ul HTTPS oficial al FreeWebService Just.ro
SOAP_ENDPOINT = "https://legislatie.just.ro/apiws/FreeWebService.svc/SOAP"

# Variabilă globală pentru stocarea token-ului activ
CURRENT_TOKEN = None

def parse_arguments():
    parser = argparse.ArgumentParser(description="Downloader XML Just.ro")
    parser.add_argument("interval", nargs="?", default="2024", help="Anul sau intervalul de ani (ex: 2024 sau 1990-1999)")
    args, unknown = parser.parse_known_args()
    return args.interval

def get_drive_service():
    service_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON")
    if not service_json:
        print_live("🛑 [EROARE CRITICĂ] Credențialele Google Drive lipsesc din mediu!")
        sys.exit(1)
    
    creds_dict = json.loads(service_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds)

def salveaza_micro_index(service, micro_data, interval_str):
    if not micro_data:
        print_live("ℹ️ [MICRO-INDEX] Nu există date noi de salvat în micro-index.")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nume_micro = f"micro_index_{interval_str}_{timestamp}.json"
    cale_local = os.path.join(ROOT_DIR, nume_micro)
    
    with open(cale_local, "w", encoding="utf-8") as f:
        json.dump(micro_data, f, ensure_ascii=False, indent=2)
    
    print_live(f"💾 [MICRO-INDEX] Se încarcă {nume_micro} pe Google Drive...")
    
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(cale_local, mimetype="application/json")
    
    file_metadata = {
        'name': nume_micro,
        'parents': [FOLDER_TEMP_INDEXES_ID]
    }
    
    try:
        service.files().create(
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True,
            fields='id'
        ).execute()
        print_live(f"✅ [MICRO-INDEX] Salvat cu succes în Drive (ID Folder: {FOLDER_TEMP_INDEXES_ID[:8]}...)")
    except Exception as e:
        print_live(f"⚠️ [MICRO-INDEX] Eroare la salvarea în Drive: {e}")
    finally:
        if os.path.exists(cale_local):
            os.remove(cale_local)

def obtine_token_sesiune(force_refresh=False):
    """Generează un token nou DOAR dacă nu există unul activ sau dacă force_refresh=True (când a expirat)."""
    global CURRENT_TOKEN
    
    if CURRENT_TOKEN and not force_refresh:
        return CURRENT_TOKEN

    print_live("🔑 [SOAP API] Solicitare token nou de sesiune (GetToken)...")
    
    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': 'http://tempuri.org/IFreeWebService/GetToken'
    }
    
    body = """<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
      <s:Body>
        <GetToken xmlns="http://tempuri.org/" />
      </s:Body>
    </s:Envelope>"""
    
    try:
        response = requests.post(SOAP_ENDPOINT, data=body, headers=headers, timeout=30)
        if response.status_code == 200:
            tree = ET.fromstring(response.text)
            for elem in tree.iter():
                if elem.tag.endswith('GetTokenResult') or elem.tag.endswith('string'):
                    if elem.text and len(elem.text.strip()) > 10:
                        CURRENT_TOKEN = elem.text.strip()
                        print_live(f"🔑 [SOAP API] Token obținut cu succes: {CURRENT_TOKEN[:12]}...")
                        return CURRENT_TOKEN
        print_live(f"⚠️ [SOAP API] Nu s-a putut genera token-ul. Status HTTP: {response.status_code}")
    except Exception as e:
        print_live(f"🛑 [SOAP API] Eroare la obținerea token-ului: {e}")
    
    return None

def cauta_acte_an_pagina(an, pagina=0, rezultate_pagina=100, reincercare=True):
    """Execută interogarea folosind token-ul curent. Cere un token nou DOAR dacă serverul indică o expirare/eroare."""
    token = obtine_token_sesiune()
    if not token:
        return []

    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': 'http://tempuri.org/IFreeWebService/Search'
    }
    
    body = f"""<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
      <s:Body>
        <Search xmlns="http://tempuri.org/">
          <model xmlns:a="http://schemas.datacontract.org/2004/07/EPI.Model.FreeWebService" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
            <a:NumarPagina>{pagina}</a:NumarPagina>
            <a:RezultatePagina>{rezultate_pagina}</a:RezultatePagina>
            <a:SearchAn>{an}</a:SearchAn>
          </model>
          <token>{token}</token>
        </Search>
      </s:Body>
    </s:Envelope>"""
    
    try:
        response = requests.post(SOAP_ENDPOINT, data=body, headers=headers, timeout=30)
        
        # Detectăm dacă token-ul a expirat sau este invalid
        status_invalida = response.status_code != 200 or "InvalidToken" in response.text or "TokenExpired" in response.text or "token" in response.text.lower() and "expir" in response.text.lower()
        
        if status_invalida:
            if reincercare:
                print_live(f"🔄 [TOKEN EXPIRAT DETECTAT] Token-ul a expirat. Solicitare token nou și reincercare pagina {pagina}...")
                obtine_token_sesiune(force_refresh=True)
                return cauta_acte_an_pagina(an, pagina, rezultate_pagina, reincercare=False)
            else:
                print_live(f"⚠️ [SOAP API] Pagina {pagina} a eșuat după reîncercare (Status HTTP {response.status_code}).")
                return []

        tree = ET.fromstring(response.text)
        acte = []
        
        for elem in tree.iter():
            if elem.tag.endswith('Id') or elem.tag.endswith('IdAct') or elem.tag.endswith('ActId'):
                if elem.text and elem.text.strip().isdigit():
                    acte.append(elem.text.strip())
        
        return list(set(acte))
        
    except Exception as e:
        print_live(f"🛑 [SOAP API] Excepție întâmpinată pe pagina {pagina}: {e}")
        if reincercare:
            print_live("🔄 Reîncercare generare token după excepție rețea/SOAP...")
            obtine_token_sesiune(force_refresh=True)
            return cauta_acte_an_pagina(an, pagina, rezultate_pagina, reincercare=False)
    
    return []

def adu_toate_actele_an(an):
    print_live(f"🔍 [SOAP API] Începe descărcarea paginată a actelor din anul {an}...")
    
    toate_actele = set()
    pagina = 0
    rezultate_pe_pagina = 100
    
    while True:
        acte_pagina = cauta_acte_an_pagina(an, pagina=pagina, rezultate_pagina=rezultate_pe_pagina)
        if not acte_pagina:
            break
            
        dimensiune_inainte = len(toate_actele)
        toate_actele.update(acte_pagina)
        
        print_live(f" 📄 [An {an}] Pagina {pagina}: +{len(acte_pagina)} acte găsite (Total cumulat: {len(toate_actele)})")
        
        if len(acte_pagina) < rezultate_pe_pagina:
            break
            
        if len(toate_actele) == dimensiune_inainte:
            break
            
        pagina += 1
        time.sleep(0.2)
        
    act_list = list(toate_actele)
    print_live(f"📊 [SOAP API] Total final: {len(act_list)} acte unice identificate pentru anul {an}.")
    return act_list

def main():
    interval_raw = parse_arguments()
    print_live(f"🚀 [DOWNLOADER] Start procesare pentru parametru/interval: {interval_raw}")
    
    if "-" in str(interval_raw):
        pasi = interval_raw.split("-")
        ani = list(range(int(pasi[0]), int(pasi[1]) + 1))
    else:
        ani = [int(interval_raw)]

    print_live(f"📅 [DOWNLOADER] Anii de procesat: {ani}")
    
    service = get_drive_service()
    micro_index = {}
    
    total_descarcate = 0
    drive_tinta = FOLDERE_XML_IDS[0]

    for an in ani:
        print_live(f"\n--- ÎNCEPUT PROCESARE ANUL {an} ---")
        acte = adu_toate_actele_an(an)
        total_acte = len(acte)
        
        if not acte:
            print_live(f"ℹ️ [ANUL {an}] Nu s-au găsit acte de descărcat.")
            continue
            
        for idx, act_id in enumerate(acte, start=1):
            nume_fisier = f"brut_XML_{act_id}.xml"
            
            micro_index[nume_fisier] = {
                "drive_id": drive_tinta,
                "tip_stocare": "individual",
                "arhiva": None
            }
            
            total_descarcate += 1
            
            if idx % 100 == 0 or idx == total_acte:
                print_live(f" 📥 Progres [An {an}]: {idx}/{total_acte} acte procesate | Total general sesiune: {total_descarcate}")

    print_live(f"\n✅ [DOWNLOADER] Procesare completă! Total general acte înregistrate: {total_descarcate}")
    salveaza_micro_index(service, micro_data, interval_raw)

if __name__ == "__main__":
    main()
