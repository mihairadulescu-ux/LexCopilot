import os
import io
import json
import csv
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Configurare ID-uri din mediu sau constante
XML_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
METADATA_FOLDER_ID = "1Cpxs20QAtAPw_RIUsOOecJON9hHPlBXf"
NUM_WORKERS = 4  # Cele 4 sesiuni/thread-uri paralele
SAVE_INTERVAL = 500  # Salvare la fiecare 500 de fișiere procesate
LOCAL_CSV_PATH = "metadate_istorice_temp.csv"

def get_drive_service():
    """Autentificare securizată folosind variabila de mediu din GitHub Secrets."""
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise ValueError("Lipsește GOOGLE_SERVICE_ACCOUNT_JSON din variabilele de mediu!")
    
    creds_info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, 
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build('drive', 'v3', credentials=creds)

def parse_xml_stream(xml_content):
    """Parsează rapid XML-ul și extrage DINAMIC toate tag-urile ca metadate."""
    metadata_list = []
    
    context = ET.iterparse(io.BytesIO(xml_content), events=('end',))
    for event, elem in context:
        # Identificăm nodurile de tip înregistrare (ajustează 'Record' dacă e cazul)
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
            
    return metadata_list

def download_and_parse(file_id, file_name, service):
    """Descarcă un singur XML de pe Drive și îl parsează dinamic."""
    try:
        from googleapiclient.http import MediaIoBaseDownload
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        
        done = False
        while not done:
            _, done = downloader.next_chunk()
            
        xml_bytes = fh.getvalue()
        return parse_xml_stream(xml_bytes)
    except Exception as e:
        print(f"[Eroare] Probleme la descărcarea/parsarea fișierului {file_name}: {str(e)}")
        return []

def save_to_drive(service, local_file_path, drive_file_id=None):
    """Urcă sau actualizează fișierul CSV pe Google Drive."""
    media = MediaFileUpload(local_file_path, mimetype='text/csv', resumable=True)
    
    if drive_file_id:
        # Actualizăm fișierul existent pe Drive (suprascriere rapidă)
        print(f"-> Se actualizează CSV-ul pe Drive (File ID: {drive_file_id})...")
        updated_file = service.files().update(
            fileId=drive_file_id,
            media_body=media
        ).execute()
        return updated_file.get('id')
    else:
        # Cream fișierul pentru prima dată în folderul destinație
        print("-> Se creează fișierul CSV nou pe Drive...")
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
    service = get_drive_service()
    
    # 1. Listăm toate fișierele XML din folderul sursă
    print("Se listează fișierele din folderul XML...")
    results = service.files().list(
        q=f"'{XML_FOLDER_ID}' in parents and trashed = false",
        fields="files(id, name)",
        pageSize=1000  # Crește valoarea dacă ai peste 1000 de fișiere
    ).execute()
    
    files = results.get('files', [])
    if not files:
        print("Nu s-a găsit niciun fișier XML în folder.")
        return

    print(f"Am găsit {len(files)} fișiere în total.")
    
    all_records = []
    processed_count = 0
    drive_csv_id = None
    
    # Ștergem fișierul CSV local anterior dacă există
    if os.path.exists(LOCAL_CSV_PATH):
        os.remove(LOCAL_CSV_PATH)
        
    # 2. Procesăm fișierele folosind cele 4 sesiuni paralele
    print(f"Pornim procesarea asincronă cu {NUM_WORKERS} lucrători...")
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        # Trimitem toate task-urile în execuție
        futures = {
            executor.submit(download_and_parse, f['id'], f['name'], service): f['name']
            for f in files
        }
        
        for future in as_completed(futures):
            file_name = futures[future]
            records = future.result()
            all_records.extend(records)
            processed_count += 1
            
            if processed_count % 100 == 0:
                print(f"Progres: {processed_count}/{len(files)} fișiere citite...")
                
            # Când atingem pragul de 500 (sau ultimul fișier), scriem local și facem sync pe Drive
            if processed_count % SAVE_INTERVAL == 0 or processed_count == len(files):
                print(f"\n[Prag atins] Salvare intermediară la {processed_count} fișiere...")
                
                if all_records:
                    # Colectăm dinamic toate header-ele unice din înregistrările acumulate până acum
                    headers = set()
                    for r in all_records:
                        headers.update(r.keys())
                    headers = sorted(list(headers))
                    
                    # Scriem fișierul local complet actualizat
                    with open(LOCAL_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=headers)
                        writer.writeheader()
                        writer.writerows(all_records)
                    
                    # Încărcăm pe Drive (la prima rulare va crea fișierul, apoi îi va da update)
                    drive_csv_id = save_to_drive(service, LOCAL_CSV_PATH, drive_csv_id)
                    print(f"[Sync finalizat] Date salvate până la fișierul #{processed_count}.\n")
                else:
                    print("Nu există date de salvat în acest calup.")

    # Curățăm fișierul local la final
    if os.path.exists(LOCAL_CSV_PATH):
        os.remove(LOCAL_CSV_PATH)

    print(f"Procesare completă! Toate cele {processed_count} fișiere au fost integrate în CSV.")

if __name__ == "__main__":
    main()
