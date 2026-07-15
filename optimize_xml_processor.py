import os
import io
import json
import csv
import xml.etree.ElementTree as ET
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Configurare ID-uri
XML_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
METADATA_FOLDER_ID = "1Cpxs20QAtAPw_RIUsOOecJON9hHPlBXf"
NUM_WORKERS = 4  
SAVE_INTERVAL = 500  

LOCAL_TIP_ACT_PATH = "tipuri_acte_temp.csv"
LOCAL_EMITENT_PATH = "emitenti_temp.csv"

def print_flush(message):
    print(message, flush=True)

def get_drive_service():
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise ValueError("Lipsește GOOGLE_SERVICE_ACCOUNT_JSON!")
    
    creds_info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, 
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build('drive', 'v3', credentials=creds, cache_discovery=False)

def parse_xml_for_normalization(xml_content):
    """
    Parsează XML-ul și extrage doar valorile unice pentru tip act și emitent.
    """
    tipuri_acte = set()
    emitenti = set()
    
    try:
        context = ET.iterparse(io.BytesIO(xml_content), events=('end',))
        for event, elem in context:
            tag_lower = elem.tag.lower()
            
            # Detecție flexibilă pentru tipuri de acte/documente
            is_tip_act = ("tip" in tag_lower and "act" in tag_lower) or ("tip" in tag_lower and "doc" in tag_lower)
            
            # Detecție flexibilă pentru emitenți
            is_emitent = "emitent" in tag_lower or "emit" in tag_lower
            
            if is_tip_act or is_emitent:
                val = elem.text.strip() if elem.text else ""
                if val and len(val) <= 250:  # Limită preventivă pentru lungimea metadatelor
                    if is_tip_act:
                        tipuri_acte.add(val)
                    if is_emitent:
                        emitenti.add(val)
                        
            elem.clear()  # Eliberăm imediat nodul din RAM
    except Exception:
        pass
        
    return list(tipuri_acte), list(emitenti)

def mark_as_processed(service, file_id, file_name):
    try:
        service.files().update(
            fileId=file_id,
            body={'appProperties': {'procesat': 'true'}},
            supportsAllDrives=True
        ).execute()
    except Exception as e:
        print_flush(f"[Avertisment] Nu s-a putut marca ca procesat {file_name}: {e}")

def download_and_parse(file_id, file_name):
    retries = 3
    for attempt in range(retries):
        try:
            service = get_drive_service()
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                _, done = downloader.next_chunk()
                
            xml_bytes = fh.getvalue()
            tipuri, emitenti = parse_xml_for_normalization(xml_bytes)
            
            mark_as_processed(service, file_id, file_name)
            return tipuri, emitenti
            
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            else:
                print_flush(f"[Eroare] Eșec definitiv la {file_name} după {retries} încercări: {str(e)}")
                return [], []

def save_to_drive(service, local_file_path, filename_on_drive, drive_file_id=None):
    media = MediaFileUpload(local_file_path, mimetype='text/csv', resumable=True)
    
    if drive_file_id:
        print_flush(f"-> Se actualizează {filename_on_drive} pe Drive (File ID: {drive_file_id})...")
        updated_file = service.files().update(
            fileId=drive_file_id,
            media_body=media,
            supportsAllDrives=True
        ).execute()
        return updated_file.get('id')
    else:
        print_flush(f"-> Se creează fișierul {filename_on_drive} pe Drive...")
        file_metadata = {
            'name': filename_on_drive,
            'parents': [METADATA_FOLDER_ID]
        }
        created_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        return created_file.get('id')

def main():
    main_service = get_drive_service()
    print_flush(f"[INFO] Se listează TOATE fișierele neprocesate din folderul XML (ID: {XML_FOLDER_ID})...")
    
    query = f"'{XML_FOLDER_ID}' in parents and trashed = false and not appProperties has {{ key='procesat' and value='true' }}"
    
    files = []
    page_token = None
    
    # Paginare infinită: strângem absolut toate fișierele disponibile pe Drive, nu doar primele 1000
    while True:
        results = main_service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageSize=1000,
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True
        ).execute()
        
        batch = results.get('files', [])
        files.extend(batch)
        print_flush(f"[INFO] S-au încărcat {len(files)} fișiere neprocesate din listă...")
        
        page_token = results.get('nextPageToken')
        if not page_token:
            break
            
    if not files:
        print_flush("[INFO] Toate fișierele din folder sunt deja procesate sau folderul este gol!")
        return

    print_flush(f"[INFO] Gata lista! Pornim procesarea pentru TOATE cele {len(files)} fișiere găsite.")
    
    all_tipuri_acte = set()
    all_emitenti = set()
    
    processed_count = 0
    drive_tip_act_id = None
    drive_emitent_id = None
    
    for path in [LOCAL_TIP_ACT_PATH, LOCAL_EMITENT_PATH]:
        if os.path.exists(path):
            os.remove(path)
            
    print_flush(f"[INFO] Pornim procesarea asincronă cu {NUM_WORKERS} procese...")
    
    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {
            executor.submit(download_and_parse, f['id'], f['name']): f['name']
            for f in files
        }
        
        for future in as_completed(futures):
            file_name = futures[future]
            try:
                tipuri, emitenti = future.result()
                all_tipuri_acte.update(tipuri)
                all_emitenti.update(emitenti)
            except Exception as exc:
                print_flush(f"[Eroare Proces] Fișierul {file_name} a generat o excepție gravă: {exc}")
                
            processed_count += 1
            print_flush(f"[{processed_count}/{len(files)}] Procesat: {file_name}")
                
            # Sincronizare periodică pe Drive la fiecare SAVE_INTERVAL sau la finalul tuturor fișierelor
            if processed_count % SAVE_INTERVAL == 0 or processed_count == len(files):
                print_flush(f"\n[Sincronizare] Salvare nomenclatoare la {processed_count} fișiere...")
                
                # 1. Salvare Nomenclator Tip Acte
                if all_tipuri_acte:
                    with open(LOCAL_TIP_ACT_PATH, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(["Valoare_Unica"])
                        for val in sorted(list(all_tipuri_acte)):
                            writer.writerow([val])
                    try:
                        drive_tip_act_id = save_to_drive(
                            main_service, 
                            LOCAL_TIP_ACT_PATH, 
                            "nomenclator_tip_act.csv", 
                            drive_tip_act_id
                        )
                    except Exception as e:
                        print_flush(f"[Eroare Sincronizare Tip Act]: {e}")
                
                # 2. Salvare Nomenclator Emitenți
                if all_emitenti:
                    with open(LOCAL_EMITENT_PATH, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(["Valoare_Unica"])
                        for val in sorted(list(all_emitenti)):
                            writer.writerow([val])
                    try:
                        drive_emitent_id = save_to_drive(
                            main_service, 
                            LOCAL_EMITENT_PATH, 
                            "nomenclator_emitent.csv", 
                            drive_emitent_id
                        )
                    except Exception as e:
                        print_flush(f"[Eroare Sincronizare Emitent]: {e}")
                
                print_flush("[Sincronizare] Finalizată cu succes pentru nomenclatoare!\n")

    # Curățenie locală finală
    for path in [LOCAL_TIP_ACT_PATH, LOCAL_EMITENT_PATH]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    print_flush(f"[FINAL] Procesare completă! S-au generat cu succes nomenclatoarele cu valori unice pentru toate cele {processed_count} fișiere.")

if __name__ == "__main__":
    main()
