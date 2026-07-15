print("[CHECKPOINT 1] Scriptul a pornit cu succes!")

import os
import io
import json
import csv
print("[CHECKPOINT 2] Importurile de bază au reușit.")

try:
    import xml.etree.ElementTree as ET
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print("[CHECKPOINT 3] Importurile concurente și XML au reușit.")
except Exception as e:
    print(f"[EROARE IMPORT 1] {str(e)}")

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    print("[CHECKPOINT 4] Importurile Google API au reușit.")
except Exception as e:
    print(f"[EROARE IMPORT 2] {str(e)}")

XML_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
METADATA_FOLDER_ID = "1Cpxs20QAtAPw_RIUsOOecJON9hHPlBXf"
NUM_WORKERS = 4
SAVE_INTERVAL = 500
LOCAL_CSV_PATH = "metadate_istorice_temp.csv"

def get_drive_service():
    print("[CHECKPOINT 6] Începe autentificarea Service Account...")
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise ValueError("Lipsește GOOGLE_SERVICE_ACCOUNT_JSON din mediu!")
    
    creds_info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, 
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    print("[CHECKPOINT 7] Credențialele au fost încărcate în memorie. Se construiește serviciul client...")
    service = build('drive', 'v3', credentials=creds)
    print("[CHECKPOINT 8] Serviciul Google Drive a fost construit cu succes!")
    return service

def main():
    print("[CHECKPOINT 5] Am intrat în funcția main()!")
    service = get_drive_service()
    
    print(f"[CHECKPOINT 9] Începe listarea fișierelor din folderul {XML_FOLDER_ID}...")
    try:
        results = service.files().list(
            q=f"'{XML_FOLDER_ID}' in parents and trashed = false",
            fields="files(id, name)",
            pageSize=10, # Punem o limită mică doar pentru test rapid
            includeItemsFromAllDrives=True,
            supportsAllDrives=True
        ).execute()
        print("[CHECKPOINT 10] Interogarea API Google Drive s-a finalizat!")
    except Exception as e:
        print(f"[EROARE API DRIVE] {str(e)}")
        return
        
    files = results.get('files', [])
    print(f"[REZULTAT TEST] S-au găsit {len(files)} fișiere la testul inițial.")

if __name__ == "__main__":
    print("[INITIALIZARE] Se apelează funcția main()...")
    main()
    print("[FINAL] Scriptul a terminat rularea de test.")
