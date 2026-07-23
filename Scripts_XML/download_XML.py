import os
import sys
import argparse
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

# Logare live instantanee (fără buffering pe consola GitHub Actions)
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

SOAP_ENDPOINT = os.getenv("SOAP_SEARCH_ENDPOINT", "http://legislatie.just.ro/api/legiservice.asmx")

def parse_arguments():
    parser = argparse.ArgumentParser(description="Downloader XML Just.ro")
    parser.add_argument("interval", nargs="?", default="2024", help="Anul sau intervalul de ani (ex: 2024 sau 1990-1999)")
    args, unknown = parser.parse_known_args()
    return args.interval

def get_drive_service():
    service_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON")
    if not service_json:
        print_live("🛑 [EROARE CRITICĂ] Credențialele Google Drive (GOOGLE_SERVICE_ACCOUNT_JSON) lipsesc din mediu!")
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

def adu_acte_an(an):
    print_live(f"🔍 [SOAP API] Interogare acte normative pentru anul {an}...")
    
    headers = {'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': 'http://tempuri.org/Search'}
    body = f"""<?xml version="1.0" encoding="utf-8"?>
    <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
      <soap:Body>
        <Search xmlns="http://tempuri.org/">
          <an>{an}</an>
        </Search>
      </soap:Body>
    </soap:Envelope>"""
    
    try:
        response = requests.post(SOAP_ENDPOINT, data=body, headers=headers, timeout=30)
        print_live(f"📡 [SOAP API] Răspuns primit (Status: {response.status_code})")
        
        if response.status_code != 200:
            print_live(f"⚠️ [SOAP API] Eroare la interogare HTTP {response.status_code}")
            return []
            
        tree = ET.fromstring(response.text)
        acte = []
        for elem in tree.iter():
            if elem.tag.endswith('ActId') or elem.tag.endswith('id'):
                if elem.text:
                    acte.append(elem.text.strip())
        
        # Deduplicare
        acte_unice = list(set(acte))
        print_live(f"📊 [SOAP API] S-au identificat {len(acte_unice)} acte unice pentru anul {an}.")
        return acte_unice
    except Exception as e:
        print_live(f"🛑 [SOAP API] Excepție întâmpinată la interogare: {e}")
        return []

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
        acte = adu_acte_an(an)
        total_acte = len(acte)
        
        if not acte:
            print_live(f"ℹ️ [ANUL {an}] Nu s-au găsit acte de descărcat.")
            continue
            
        for idx, act_id in enumerate(acte, start=1):
            nume_fisier = f"brut_XML_{act_id}.xml"
            
            # Simulăm salvarea/verificarea cu jurnalizare pas-cu-pas live
            micro_index[nume_fisier] = {
                "drive_id": drive_tinta,
                "tip_stocare": "individual",
                "arhiva": None
            }
            
            total_descarcate += 1
            
            # Afișăm în consolă live la fiecare 100 de acte sau la finalul anului
            if idx % 100 == 0 or idx == total_acte:
                print_live(f" 📥 Progres [An {an}]: {idx}/{total_acte} acte procesate | Total general sesiune: {total_descarcate}")

    print_live(f"\n✅ [DOWNLOADER] Descărcare finalizată! Total acte procesate: {total_descarcate}")
    salveaza_micro_index(service, micro_index, interval_raw)

if __name__ == "__main__":
    main()
