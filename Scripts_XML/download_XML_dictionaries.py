import os
import sys
import io
import json
import csv
import xml.etree.ElementTree as ET
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Culori pentru loguri curate în consolă
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")

# Interval implicit extras din variabilele globale de mediu
START_YEAR = int(os.getenv("START_YEAR", "2000"))
END_YEAR = int(os.getenv("END_YEAR", "2026"))


def obtine_drive():
    print("🔑 [Get Tags XML] Conectare Google Drive...")
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        info = json.loads(github_secret)
        creds = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
    else:
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul '{credentials_path}'!")
        creds = Credentials.from_service_account_file(
            credentials_path, scopes=["https://www.googleapis.com/auth/drive"]
        )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def extrage_taguri_din_xml(continut_xml):
    emitent = None
    tip_act = None
    try:
        context = ET.iterparse(io.StringIO(continut_xml), events=("end",))
        for event, elem in context:
            tag_curat = elem.tag.split('}')[-1].lower()
            if tag_curat in ["emitent", "autor", "institutie"]:
                if elem.text and elem.text.strip():
                    emitent = elem.text.strip()
            elif tag_curat in ["tipact", "tip_act", "document_type"]:
                if elem.text and elem.text.strip():
                    tip_act = elem.text.strip()
            if emitent and tip_act:
                break
    except ET.ParseError:
        pass
    return emitent, tip_act


def citeste_csv_existent(cale_fisier):
    elemente = set()
    if os.path.exists(cale_fisier):
        try:
            with open(cale_fisier, mode="r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for rand in reader:
                    if rand and rand[0].strip():
                        elemente.add(rand[0].strip())
        except Exception:
            pass
    return elemente


def salveaza_lista_simpla(cale_fisier, header, set_date):
    with open(cale_fisier, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([header])
        for item in sorted(list(set_date)):
            writer.writerow([item])


def proceseaza_segment_xml(an_start, an_stop):
    if not TARGET_FOLDERS_RAW:
        print(f"{ROSU}❌ Lipseste ID-ul folderului XML (DRIVE_FOLDER_XML).{RESET}")
        return

    # Extragere curată ierarhie foldere (Folder 1, Folder 2 etc.)
    clean_raw = TARGET_FOLDERS_RAW.replace('"', '').replace("'", "").replace("\n", "").replace("\r", "").strip()
    folder_ids = [fid.strip() for fid in clean_raw.split(",") if fid.strip()]
    
    if not folder_ids:
        folder_ids = [
            "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
            "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
            "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
            "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2"
        ]

    service = obtine_drive()
    
    # Nume unice bazate pe intervalul matricei ca să evităm coliziunile la rularea paralelă
    cale_emitenti = f"lista_emitenti_{an_start}_{an_stop}.csv"
    cale_acte = f"lista_tip_acte_{an_start}_{an_stop}.csv"
    
    set_emitenti = citeste_csv_existent(cale_emitenti)
    set_acte = citeste_csv_existent(cale_acte)
    
    print(f"{VERDE}🔍 Pasul 1: Scanare ierarhică fișiere neprocesate pentru intervalul {an_start} - {an_stop}...{RESET}")
    fisiere_xml = []
    
    # Colectăm doar XML-urile asociate anilor din această bucată de matrice
    for target_year in range(an_start, an_stop + 1):
        for folder_id in folder_ids:
            page_token = None
            
            # Query optimizat militar direct pe prefixul anului și flag-ul processed: false
            query = (
                f"'{folder_id}' in parents and name contains 'brut_legislatie_{target_year}_pag' and "
                f"not appProperties has {{ key='processed' and value='true' }} and trashed = false"
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
                    
                    fisiere_xml.extend(response.get("files", []))
                    page_token = response.get("nextPageToken", None)
                    if not page_token:
                        break
                except Exception as e:
                    break

    total_fisiere = len(fisiere_xml)
    if total_fisiere == 0:
        print(f"🎉 All clear! Toate fișierele XML pentru intervalul {an_start}-{an_stop} sunt complet procesate.")
        return

    print(f"📊 Am identificat {total_fisiere} fișiere XML noi de analizat în acest segment paralel.", flush=True)

    # Procesarea secvențială a documentelor găsite în segment
    for idx, fx in enumerate(fisiere_xml, 1):
        nume = fx["name"]
        fid = fx["id"]
        
        print(f"⏳ [{idx}/{total_fisiere}] Extragere dictionar: {nume}...", flush=True)
        try:
            request = service.files().get_media(fileId=fid)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            
            fh.seek(0)
            continut_text = fh.getvalue().decode('utf-8', errors='ignore')
            
            emitent, tip_act = extrage_taguri_din_xml(continut_text)
            if emitent:
                set_emitenti.add(emitent)
            if tip_act:
                set_acte.add(tip_act)
                
            # Adăugăm flag-ul processed: true direct pe fișierul din Google Drive
            service.files().update(
                fileId=fid,
                body={"appProperties": {"processed": "true"}},
                supportsAllDrives=True
            ).execute()
            print(f"    ✅ Valori reținute. Fișier etichetat cu succes.")
            
        except Exception as e:
            print(f"    ❌ {ROSU}[Eroare]{RESET} Imposibil de citit/actualizat {nume}: {str(e)[:60]}")

    # Salvarea nomenclatoarelor unice per fir de execuție
    salveaza_lista_simpla(cale_emitenti, "Emitent", set_emitenti)
    salveaza_lista_simpla(cale_acte, "Tip_Act", set_acte)
    print(f"\n🏁 {VERDE}Nomenclatoare finalizate pentru segmentul {an_start} - {an_stop}! Salvare în {cale_emitenti} și {cale_acte}{RESET}")


if __name__ == "__main__":
    # Interceptăm argumentele numerice transmise de Matrix-ul din YAML
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
        
    print(f"{VERDE}🎯 [Config Matrice Dictionar] Rulare pe segmentul: {an_s} - {an_f}{RESET}", flush=True)
    proceseaza_segment_xml(an_s, an_f)
