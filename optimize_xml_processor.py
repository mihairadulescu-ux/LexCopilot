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

# Configurare ID-uri din mediu sau constante
XML_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
METADATA_FOLDER_ID = "1Cpxs20QAtAPw_RIUsOOecJON9hHPlBXf"
NUM_WORKERS = 4  # Numărul de procese paralele
SAVE_INTERVAL = 500  # Salvare la fiecare 500 de fișiere procesate
LOCAL_CSV_PATH = "metadate_istorice_temp.csv"

def print_flush(message):
    """Printează și golește buffer-ul instantaneu pentru GitHub Actions."""
    print(message, flush=True)

def get_drive_service():
    """Construiește o instanță curată și izolată a serviciului Google Drive."""
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise ValueError("Lipsește GOOGLE_SERVICE_ACCOUNT_JSON din variabilele de mediu!")
    
    creds_info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, 
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    # Folosim explicit cache_discovery=False pentru a evita scrierea concurentă de fișiere cache în procese paralele
    return build('drive', 'v3', credentials=creds, cache_discovery=False)

def parse_xml_stream(xml_content):
    """Parsează rapid XML-ul și extrage toate tag-urile ca metadate."""
    metadata_list = []
    try:
        context = ET.iterparse(io.BytesIO(xml_content), events=('end',))
        for event, elem in context:
            if len(elem) > 0 and elem.tag != 'Root': 
                record = {}
                for child in elem:
                    if child.text and child.text.strip():
                        record[child.tag] = child.text.strip()
                    for attr_name, attr_val in child.attrib.items():
                        record[f"{child.tag}_{attr_name}"] = attr_val
                
                if record:
                    metadata_list.append(record)
                    
                elem.clear()  # Eliberăm imediat memoria RAM
    except Exception as parse_err:
        # Dacă XML-ul este parțial corupt sau gol
        pass
            
    return metadata_list

def download_and_parse(file_id, file_name):
    """
    Descarcă un singur XML. Rulează într-un proces complet izolat.
    Include 3 încercări automate (retries) în caz de eroare de rețea.
    """
    retries = 3
    for attempt in range(retries):
        try:
            # Creăm clientul Google special în interiorul procesului, izolat de ceilalți
            service = get_drive_service()
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                _, done = downloader.next_chunk()
                
            xml_bytes = fh.getvalue()
            records = parse_xml_stream(xml_bytes)
            return records
            
        except Exception as e:
            if attempt < retries - 1:
                # Așteptăm puțin înainte de a reîncerca
                time.sleep(1.5 * (attempt + 1))
                continue
            else:
                print_flush(f"[Eroare] Eșec definitiv la fișierul {file_name} după {retries} încercări: {str(e)}")
                return []

def save_to_drive(service, local_file_path, drive_file_id=None):
    """Urcă sau actualizează fișierul CSV pe Google Drive."""
    media = MediaFileUpload(local_file_path, mimetype='text/csv', resumable=True)
    
    if drive_file_id:
        print_flush(f"-> Se actualizează CSV-ul pe Drive (File ID: {drive_file_id})...")
        updated_file = service.files().update(
            fileId=drive_file_id,
            media_body=media
        ).execute()
        return updated_file.get('id')
    else:
        print_flush("-> Se creează fișierul CSV nou pe Drive...")
        file_metadata = {
            'name': 'metadate_istorice_optimizat.csv',
            'parents': [METADATA_FOLDER_ID]
        }
        created_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        return created_file.get('id')

def main():
    # Serviciul principal folosit pentru listare și scriere finală
    main_service = get_drive_service()
    
    # 1. Listăm toate fișierele XML din folderul sursă
    print_flush(f"[INFO] Se listează fișierele din folderul XML (ID: {XML_FOLDER_ID})...")
    
    results = main_service.files().list(
        q=f"'{XML_FOLDER_ID}' in parents and trashed = false",
        fields="files(id, name)",
        pageSize=1000,
        includeItemsFromAllDrives=True,
        supportsAllDrives=True
    ).execute()
    
    files = results.get('files', [])
    if not files:
        print_flush("[Eroare] Nu s-a găsit niciun fișier XML în folder.")
        return

    print_flush(f"[INFO] Succes! Am găsit {len(files)} fișiere în total.")
    
    all_records = []
    processed_count = 0
    drive_csv_id = None
    
    if os.path.exists(LOCAL_CSV_PATH):
        os.remove(LOCAL_CSV_PATH)
        
    # 2. Procesăm fișierele în paralel folosind PROCESE în loc de THREAD-URI
    print_flush(f"[INFO] Pornim procesarea asincronă cu {NUM_WORKERS} procese izolate...")
    
    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
        # Trimitem joburile către procese separate
        futures = {
            executor.submit(download_and_parse, f['id'], f['name']): f['name']
            for f in files
        }
        
        for future in as_completed(futures):
            file_name = futures[future]
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as exc:
                print_flush(f"[Eroare Proces] Fișierul {file_name} a generat o excepție gravă: {exc}")
                
            processed_count += 1
            print_flush(f"[{processed_count}/{len(files)}] Procesat cu succes: {file_name}")
                
            # Sincronizare periodică pe Drive
            if processed_count % SAVE_INTERVAL == 0 or processed_count == len(files):
                print_flush(f"\n[Sincronizare] Salvare intermediară la {processed_count} fișiere...")
                
                if all_records:
                    headers = set()
                    for r in all_records:
                        headers.update(r.keys())
                    headers = sorted(list(headers))
                    
                    with open(LOCAL_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=headers)
                        writer.writeheader()
                        writer.writerows(all_records)
                    
                    # Upload din procesul principal
                    drive_csv_id = save_to_drive(main_service, LOCAL_CSV_PATH, drive_csv_id)
                    print_flush(f"[Sincronizare] Finalizată cu succes pentru primele {processed_count} fișiere!\n")
                else:
                    print_flush("[Sincronizare] Nu există date noi în acest calup.\n")

    if os.path.exists(LOCAL_CSV_PATH):
        os.remove(LOCAL_CSV_PATH)

    print_flush(f"[FINAL] Procesare completă! Toate cele {processed_count} fișiere au fost integrate în CSV.")

if __name__ == "__main__":
    main()
