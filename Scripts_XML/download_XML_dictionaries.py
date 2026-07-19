import os
import sys
import io
import json
import csv
import xml.etree.ElementTree as ET
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")


def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
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


def proceseaza_segment_xml():
    if not TARGET_FOLDERS_RAW:
        print(f"{ROSU}❌ Lipseste ID-ul folderului XML (DRIVE_FOLDER_XML).{RESET}")
        return

    folder_ids = [fid.strip() for fid in TARGET_FOLDERS_RAW.split(",") if fid.strip()]
    service = obtine_drive()
    
    cale_emitenti = "lista_emitenti.csv"
    cale_acte = "lista_tip_acte.csv"
    set_emitenti = citeste_csv_existent(cale_emitenti)
    set_acte = citeste_csv_existent(cale_acte)
    
    print(f"{VERDE}🔍 Pasul 1: Scanare fișiere neprocesate în locații...{RESET}")
    fisiere_xml = []
    
    for folder_id in folder_ids:
        page_token = None
        query = (
            f"'{folder_id}' in parents and name contains '.xml' and "
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
                print(f"{ROSU}⚠️ Ignorat folder inaccesibil sau inexistent (ID: {folder_id}).{RESET}")
                break

    total_fisiere = len(fisiere_xml)
    if total_fisiere == 0:
        print("🎉 Toate fișierele XML accesibile sunt complet procesate!")
        return

    print(f"📊 Am găsit {total_fisiere} fișiere XML noi de analizat în folderele valide.", flush=True)

    for idx, fx in enumerate(fisiere_xml, 1):
        nume = fx["name"]
        fid = fx["id"]
        
        print(f"⏳ [{idx}/{total_fisiere}] Extragere dicționar: {nume}...", flush=True)
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
                
            service.files().update(
                fileId=fid,
                body={"appProperties": {"processed": "true"}},
                supportsAllDrives=True
            ).execute()
            print(f"    ✅ Valori reținute. Fișier etichetat.")
        except Exception as e:
            print(f"    ❌ {ROSU}[Eroare]{RESET} Imposibil de citit {nume}: {str(e)[:60]}")

    salveaza_lista_simpla(cale_emitenti, "Emitent", set_emitenti)
    salveaza_lista_simpla(cale_acte, "Tip_Act", set_acte)
    print(f"\n🏁 {VERDE}Nomenclatoare actualizate cu succes!{RESET}")


if __name__ == "__main__":
    proceseaza_segment_xml()
