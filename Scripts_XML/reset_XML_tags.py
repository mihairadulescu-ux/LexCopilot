import os
import sys
import json
import time
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Culori pentru loguri curate în consolă
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")

# Configurare interval implicit din variabile de mediu
START_YEAR = int(os.getenv("START_YEAR", "2000"))
END_YEAR = int(os.getenv("END_YEAR", "2026"))


def obtine_drive():
    print("🔑 [Reset XML] Conectare Google Drive...")
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        info = json.loads(github_secret)
        creds = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
    else:
        # Suport rulare locală backend
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul '{credentials_path}'!")
        creds = Credentials.from_service_account_file(
            credentials_path, scopes=["https://www.googleapis.com/auth/drive"]
        )
        
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def reseteaza_atribute_xml(an_start, an_stop):
    if not TARGET_FOLDERS_RAW:
        print(f"{ROSU}🛑 Eroare configurare: DRIVE_FOLDER_XML lipsește din mediu!{RESET}")
        return

    # Extragere curată ierarhie foldere (Folder 1, Folder 2 etc.)
    clean_raw = TARGET_FOLDERS_RAW.replace('"', '').replace("'", "").replace("\n", "").replace("\r", "").strip()
    folder_ids = [fid.strip() for fid in clean_raw.split(",") if fid.strip()]
    
    if not folder_ids:
        # Fallback de siguranță pe folderele tale cunoscute
        folder_ids = [
            "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
            "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
            "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
            "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
        ]

    service = obtine_drive()
    print(f"{VERDE}🚀 Inițiere resetare matrice paralelă pentru intervalul: {an_start} - {an_stop}...{RESET}")

    fisiere_marcate = []
    
    # Procesăm pe rând fiecare an alocat acestui fir de execuție
    for target_year in range(an_start, an_stop + 1):
        print(f"\n⚡ [Scanare Istoric] Identificare XML-uri deja procesate pentru anul {target_year}...")
        
        # Luăm la rând cele 4 foldere din ierarhie
        for folder_id in folder_ids:
            page_token = None
            
            # Query ultra-optimizat: țintim direct fișierele anului din buclă, marcate cu true
            query = (
                f"'{folder_id}' in parents and name contains 'brut_legislatie_{target_year}_pag' and "
                f"appProperties has {{ key='processed' and value='true' }} and trashed = false"
            )
            
            while True:
                try:
                    response = service.files().list(
                        q=query, 
                        spaces='drive',
                        fields="nextPageToken, files(id, name)", 
                        pageToken=page_token, 
                        pageSize=1000,
                        supportsAllDrives=True, 
                        includeItemsFromAllDrives=True
                    ).execute()
                    
                    fisiere_marcate.extend(response.get("files", []))
                    page_token = response.get("nextPageToken", None)
                    if not page_token:
                        break
                except Exception as e:
                    # Dacă un folder e temporar inaccesibil, continuăm scanarea în restul
                    break

    if not fisiere_marcate:
        print(f"\n{VERDE}✨ Nu s-a găsit niciun XML din intervalul {an_start}-{an_stop} marcat ca procesat.{RESET}")
        return

    total_fisiere = len(fisiere_marcate)
    print(f"\n{GALBEN}⚙️ Începe ștergerea flag-urilor (revenire la starea neprocesat) pentru {total_fisiere} fișiere...{RESET}", flush=True)
    
    # Executăm resetarea efectivă
    for idx, xml in enumerate(fisiere_marcate, 1):
        try:
            service.files().update(
                fileId=xml["id"], 
                body={"appProperties": {"processed": "false"}}, 
                supportsAllDrives=True
            ).execute()
            
            if idx % 20 == 0 or idx == total_fisiere:
                print(f"    ✅ [{idx}/{total_fisiere}] Resetat flag 'processed' -> false pentru: {xml['name']}", flush=True)
        except Exception as e:
            print(f"{ROSU}⚠️ Eroare resetare la fișierul {xml['name']}: {e}{RESET}", flush=True)
            continue

    print(f"\n{VERDE}🎉 [SUCCES] Resetare finalizată pentru segmentul {an_start} - {an_stop}!{RESET}\n")


if __name__ == "__main__":
    # Interceptăm argumentele numerice din Matrix-ul YAML (exact ca la download)
    argumente_numerice = []
    
    for arg in sys.argv[1:]:
        piese = arg.split()
        for piesa in piese:
            if piesa.isdigit():
                argumente_numerice.append(int(piesa))

    if len(argumente_numerice) == 1:
        an_s = argumente_numerice[0]
        an_f = argumente_numerice[0]
    elif len(argumente_numerice) >= 2:
        an_s = argumente_numerice[0]
        an_f = argumente_numerice[1]
    else:
        an_s = START_YEAR
        an_f = END_YEAR
        
    print(f"{VERDE}🎯 [Config Matrice Reset] Rulare pe segmentul: {an_s} - {an_f}{RESET}", flush=True)
    reseteaza_atribute_xml(an_s, an_f)
