import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

XML_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"

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

def reset_processed_status():
    service = get_drive_service()
    print_flush("[RESET] Se listează fișierele marcate ca procesate...")
    
    # Căutăm doar fișierele care au appProperties 'procesat' setat pe 'true'
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
            
    if not files_to_reset:
        print_flush("[RESET] Nu s-a găsit niciun fișier marcat ca procesat.")
        return
        
    print_flush(f"[RESET] S-au găsit {len(files_to_reset)} fișiere care vor fi resetate.")
    
    for idx, f in enumerate(files_to_reset, 1):
        try:
            # Setarea valorii la None șterge cheia respectivă din metadata Google Drive
            service.files().update(
                fileId=f['id'],
                body={'appProperties': {'procesat': None}},
                supportsAllDrives=True
            ).execute()
            print_flush(f"[{idx}/{len(files_to_reset)}] Resetat status pentru: {f['name']}")
        except Exception as e:
            print_flush(f"[Eroare Reset] Eșec la {f['name']}: {e}")
            
    print_flush("[RESET] Resetarea atributelor a fost finalizată cu succes!")

if __name__ == '__main__':
    reset_processed_status()
