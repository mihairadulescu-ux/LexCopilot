# Culori pentru un log frumos în consolă
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

# CONFIGURARE DIN MEDIU
DRIVE_FOLDER_XML = os.getenv("DRIVE_FOLDER_XML")


def get_drive_service():
    """Autentifică robotul în Google Drive."""
    scopes = ["https://www.googleapis.com/auth/drive"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul '{credentials_path}'!")
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def reseteaza_atribute_procesare():
    print(f"{GALBEN}🔄 Inițiere resetare atribute de procesare pentru XML-uri...{RESET}")
    
    if not DRIVE_FOLDER_XML:
        print(f"{ROSU}🛑 Eroare configurare: DRIVE_FOLDER_XML lipsește!{RESET}")
        return

    service = get_drive_service()
    
    # QUERY CORECTAT: Filtrăm exclusiv după descriere și mimeType, ocolind eroarea de 'name contains'
    query = f"'{DRIVE_FOLDER_XML}' in parents and description = 'processed_for_tags: true' and mimeType = 'application/xml' and trashed = false"
    
    page_token = None
    fisiere_de_resetat = []
    
    print(f"🔍 Identificăm fișierele marcate în Drive...")
    while True:
        try:
            response = service.files().list(
                q=query, spaces='drive', fields='nextPageToken, files(id, name)',
                pageToken=page_token, pageSize=500, supportsAllDrives=True, includeItemsFromAllDrives=True
            ).execute()
            
            fisiere_de_resetat.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if not page_token:
                break
        except Exception as e:
            print(f"{ROSU}🛑 Eroare la interogarea Drive API: {e}{RESET}")
            return

    if not fisiere_de_resetat:
        print(f"{VERDE}✨ Nu există fișiere marcate. Totul este deja pregătit pentru o căutare fresh!{RESET}")
        return

    print(f"🧠 Am găsit {len(fisiere_de_resetat)} fișiere de resetat. Începem curățarea metadatelor...")
    
    for idx, fisier in enumerate(fisiere_de_resetat, 1):
        f_id = fisier['id']
        f_nume = fisier['name']
        
        try:
            # Pentru a șterge complet descrierea în API v3, îi pasăm un string gol
            service.files().update(fileId=f_id, body={'description': ''}, supportsAllDrives=True).execute()
            
            if idx % 100 == 0 or idx == len(fisiere_de_resetat):
                print(f"   ⚙️ [{idx}/{len(fisiere_de_resetat)}] Resetat cu succes: {f_nume}")
                
        except Exception as e:
            print(f"{ROSU}⚠️ Nu s-a putut reseta metadata pentru {f_nume}: {e}{RESET}")
            continue

    print(f"\n{VERDE}🎉 Resetare completă! Toate cele {len(fisiere_de_resetat)} XML-uri sunt libere acum.{RESET}")


if __name__ == "__main__":
    reseteaza_atribute_procesare()
