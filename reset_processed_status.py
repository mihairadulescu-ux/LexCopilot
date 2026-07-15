import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.oauth2 import service_account
from googleapiclient.discovery import build

XML_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
MAX_WORKERS = 10  # Numărul de thread-uri paralele (poți urca la 15-20 dacă vrei și mai rapid)

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

def reset_single_file(file_id, file_name):
    """Resetează statusul pentru un singur fișier."""
    try:
        service = get_drive_service()
        service.files().update(
            fileId=file_id,
            body={'appProperties': {'procesat': None}},
            supportsAllDrives=True
        ).execute()
        return True, file_name
    except Exception as e:
        return False, f"Eșec la {file_name}: {e}"

def reset_processed_status():
    service = get_drive_service()
    print_flush("[RESET] Se listează fișierele marcate ca procesate...")
    
    # Căutăm DOAR fișierele care au appProperties 'procesat' setat pe 'true'
    query = f"'{XML_FOLDER_ID}' in parents and trashed = false and appProperties has {{ key='procesat' and value='true' }}"
    
    files_to_reset = []
    page_token = None
    
    while True:
        results = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageSize=1000,
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True
        ).execute()
        
        files_to_reset.extend(results.get('files', []))
        page_token = results.get('nextPageToken')
        if not page_token:
            break
            
    total_files = len(files_to_reset)
    if total_files == 0:
        print_flush("[RESET] Nu s-a găsit niciun fișier marcat ca procesat. Totul este curat.")
        return
        
    print_flush(f"[RESET] S-au găsit {total_files} fișiere procesate. Pornim resetarea paralelă cu {MAX_WORKERS} thread-uri...")
    
    success_count = 0
    fail_count = 0
    
    # Folosim ThreadPoolExecutor pentru execuție paralelă (I/O-bound)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(reset_single_file, f['id'], f['name']): f['name']
            for f in files_to_reset
        }
        
        for future in as_completed(futures):
            success, info = future.result()
            if success:
                success_count += 1
                if success_count % 50 == 0 or success_count == total_files:
                    print_flush(f"[RESET] Progres: {success_count}/{total_files} fișiere resetate.")
            else:
                fail_count += 1
                print_flush(f"[Eroare Reset] {info}")
                
    print_flush(f"[RESET] Operațiunea s-a încheiat! Succes: {success_count}, Eșecuri: {fail_count}.")

if __name__ == '__main__':
    reset_processed_status()
