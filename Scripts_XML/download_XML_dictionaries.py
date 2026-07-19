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
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
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

    # Regex-uri ultra-rapide care extrag textul dintre taguri ignorand complet namespace-urile
    regex_emitent = re.compile(r"<[^:>]*:?Emitent>(.*?)</[^:>]*:?Emitent>", re.DOTALL)
    regex_tip_act = re.compile(r"<[^:>]*:?TipAct>(.*?)</[^:>]*:?TipAct>", re.DOTALL)

    for target_year in ani_procesare:
        print(f"\n{GALBEN}⚡ [Dictionare] Scanare fișiere pentru anul {target_year}...{RESET}")
        fișiere_an = []

        for folder_id in FOLDER_IDS:
            page_token = None
            query = f"'{folder_id}' in parents and name contains 'brut_legislatie_{target_year}_pag' and trashed = false"

            try:
                while True:
                    response = service.files().list(
                        q=query, 
                        spaces='drive', 
                        fields='nextPageToken, files(id, name)',
                        pageSize=1000,
                        pageToken=page_token,
                        supportsAllDrives=True, 
                        includeItemsFromAllDrives=True
                    ).execute()

                    fișiere_an.extend(response.get('files', []))
                    page_token = response.get('nextPageToken', None)
                    if not page_token:
                        break
            except Exception as e:
                print(f"{ROSU}⚠️ Eroare scanare folder {folder_id[:8]}...: {e}{RESET}")
                continue

        total_gasite = len(fișiere_an)
        print(f"{VERDE}📦 Am descoperit {total_gasite} fișiere XML pentru anul {target_year}. Începe descărcarea...{RESET}")

        if total_gasite == 0:
            continue

        for idx_f, file in enumerate(fișiere_an, 1):
            if idx_f % 250 == 0 or idx_f == total_gasite:
                print(f"   ⚙️ Procesat text: {idx_f}/{total_gasite}...")
                
            try:
                cerere = service.files().get_media(fileId=file['id'])
                fh = io.BytesIO()
                descarcare = MediaIoBaseDownload(fh, cerere)
                gata = False
                while not gata:
                    _, gata = descarcare.next_chunk()
                
                # Decodăm textul brut direct
                xml_text = fh.getvalue().decode("utf-8", errors="ignore")
                
                # Extragere prin regex (evită crash-ul de parser XML dacă fișierul e trunchiat sau are caractere speciale)
                for em in regex_emitent.findall(xml_text):
                    val = em.strip()
                    if val: emitenti_gasiti.add(val)
                    
                for ta in regex_tip_act.findall(xml_text):
                    val = ta.strip()
                    if val: tipuri_acte_gasite.add(val)
                        
            except Exception:
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
            
    print(f"{VERDE}✅ Fișierele {cale_emitenti} și {cale_acte} au fost generate cu succes!{RESET}")

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
