import os
import sys
import csv
import json
import re
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")
FOLDER_IDS = []

if TARGET_FOLDERS_RAW.strip():
    clean_raw = TARGET_FOLDERS_RAW.replace('"', '').replace("'", "").replace("\n", "").replace("\r", "").strip()
    FOLDER_IDS = [fid.strip() for fid in clean_raw.split(",") if fid.strip()]

if not FOLDER_IDS:
    FOLDER_IDS = [
        "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
        "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
        "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
        "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
    ]

def get_drive_service():
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

def extrage_taguri_din_matrice(service, ani_procesare):
    emitenti_gasiti = set()
    tipuri_acte_gasite = set()

    regex_emitent = re.compile(r"<[^:>]*:?Emitent>(.*?)</[^:>]*:?Emitent>", re.DOTALL)
    regex_tip_act = re.compile(r"<[^:>]*:?TipAct>(.*?)</[^:>]*:?TipAct>", re.DOTALL)

    CHUNK_SIZE = 100

    for target_year in ani_procesare:
        print(f"\n{GALBEN}⚡ [Dictionare] Scanare pentru anul {target_year}...{RESET}")
        
        for folder_id in FOLDER_IDS:
            page_token = None
            # Căutare curată acceptată de API: cerem și description în fields pentru filtrare manuală
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_{target_year}_pag' and trashed = false"

            try:
                while True:
                    response = service.files().list(
                        q=query, 
                        spaces='drive', 
                        fields='nextPageToken, files(id, name, description)',
                        pageSize=CHUNK_SIZE,
                        pageToken=page_token,
                        supportsAllDrives=True, 
                        includeItemsFromAllDrives=True
                    ).execute()

                    all_files = response.get('files', [])
                    if not all_files:
                        page_token = response.get('nextPageToken', None)
                        if not page_token:
                            break
                        continue

                    # Filtrare în Python: selectăm doar pe cele care NU sunt marcate ca processed=true
                    micro_task_files = [f for f in all_files if f.get('description', '') != 'processed=true']

                    if micro_task_files:
                        print(f"📦 [Micro-Task] Procesez {len(micro_task_files)} fișiere noi în folderul {folder_id[:8]}...")

                        for file in micro_task_files:
                            try:
                                cerere = service.files().get_media(fileId=file['id'])
                                fh = io.BytesIO()
                                descarcare = MediaIoBaseDownload(fh, cerere)
                                gata = False
                                while not gata:
                                    _, gata = descarcare.next_chunk()
                                
                                xml_text = fh.getvalue().decode("utf-8", errors="ignore")
                                
                                for em in regex_emitent.findall(xml_text):
                                    val = em.strip()
                                    if val: emitenti_gasiti.add(val)
                                    
                                for ta in regex_tip_act.findall(xml_text):
                                    val = ta.strip()
                                    if val: tipuri_acte_gasite.add(val)

                                # Marcare ca procesat
                                service.files().update(
                                    fileId=file['id'],
                                    body={'description': 'processed=true'},
                                    fields='id',
                                    supportsAllDrives=True
                                ).execute()

                            except Exception:
                                continue
                    
                    page_token = response.get('nextPageToken', None)
                    if not page_token:
                        break

            except Exception as e:
                print(f"{ROSU}⚠️ Eroare pe folderul {folder_id[:8]}: {e}{RESET}")
                continue

    # Export CSV
    string_ani = "_".join([str(a) for a in ani_procesare])
    cale_emitenti = f"lista_emitenti_{string_ani}.csv"
    cale_acte = f"lista_tip_acte_{string_ani}.csv"
    
    with open(cale_emitenti, mode='w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['Emitent'])
        for e in sorted(list(emitenti_gasiti)):
            writer.writerow([e])
            
    with open(cale_acte, mode='w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['Tip_Act'])
        for t in sorted(list(tipuri_acte_gasite)):
            writer.writerow([t])
            
    print(f"{VERDE}✅ [Gata] Fragmentele pentru {string_ani} au fost salvate!{RESET}")

if __name__ == "__main__":
    argumente_numerice = []
    for arg in sys.argv[1:]:
        piese = arg.split()
        for piesa in piese:
            if piesa.isdigit():
                argumente_numerice.append(int(piesa))

    if not argumente_numerice:
        print(f"{ROSU}🛑 Eroare: Lipsesc anii ca parametru!{RESET}")
        sys.exit(1)
        
    drive_service = get_drive_service()
    extrage_taguri_din_matrice(drive_service, argumente_numerice)
