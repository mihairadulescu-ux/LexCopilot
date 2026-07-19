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

FOLDER_XML_ID = os.getenv("DRIVE_FOLDER_XML")


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
    """Încarcă elementele existente din CSV-ul local pentru a preveni duplicatele."""
    elemente = set()
    if os.path.exists(cale_fisier):
        try:
            with open(cale_fisier, mode="r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # Sărim peste header
                for rand in reader:
                    if rand and rand[0].strip():
                        elemente.add(rand[0].strip())
        except Exception:
            pass
    return elemente


def salveaza_lista_simpla(cale_fisier, header, set_date):
    """Salvează un set sortat alfabetic într-un CSV curat cu o singură coloană."""
    with open(cale_fisier, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([header])
        for item in sorted(list(set_date)):
            writer.writerow([item])


def proceseaza_segment_xml():
    if not FOLDER_XML_ID:
        print(f"{ROSU}❌ Lipseste ID-ul folderului XML (DRIVE_FOLDER_XML).{RESET}")
        return

    service = obtine_drive()
    
    # Încărcăm listele curente pentru a funcționa incremental
    cale_emitenti = "lista_emitenti.csv"
    cale_acte = "lista_tip_acte.csv"
    
    set_emitenti = citeste_csv_existent(cale_emitenti)
    set_acte = citeste_csv_existent(cale_acte)
    
    print(f"{VERDE}🔍 Pasul 1: Scanare fișiere neprocesate în Drive...{RESET}")
    # Filtrare nativă API: colectăm doar fișierele fără proprietatea processed=true
    query = (
        f"'{FOLDER_XML_ID}' in parents and name contains '.xml' "
        f"and appProperties/processed != 'true' and trashed = false"
    )
    
    fisiere_xml = []
    page_token = None
    
    while True:
        response = service.files().list(
            q=query, spaces='drive', 
            fields="nextPageToken, files(id, name)",
            pageToken=page_token, pageSize=1000, supportsAllDrives=True,
            includeItemsFromAllDrives=True, corpora="allDrives"
        ).execute()
        
        fisiere_xml.extend(response.get("files", []))
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break

    total_fisiere = len(fisiere_xml)
    if total_fisiere == 0:
        print("🎉 Toate fișierele XML din folder sunt complet procesate!")
        return

    print(f"📊 Am găsit {total_fisiere} fișiere XML noi de scanat.", flush=True)

    for idx, fx in enumerate(fisiere_xml, 1):
        nume = fx["name"]
        fid = fx["id"]
        
        print(f"⏳ [{idx}/{total_fisiere}] Extragere dicționar: {nume}...", flush=True)
        
        try:
            # 1. Descărcare eficientă în stream memorie
            request = service.files().get_media(fileId=fid)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            
            fh.seek(0)
            continut_text = fh.getvalue().decode('utf-8', errors='ignore')
            
            # 2. Extracție etichete
            emitent, tip_act = extrage_taguri_din_xml(continut_text)
            
            if emitent:
                set_emitenti.add(emitent)
            if tip_act:
                set_acte.add(tip_act)
                
            # 3. Aplicare flag 'processed' direct în metadatele Google Drive
            service.files().update(
                fileId=fid,
                body={"appProperties": {"processed": "true"}},
                supportsAllDrives=True
            ).execute()
            
            print(f"    ✅ Valori reținute. Fișier marcat ca procesat în Cloud.")
            
        except Exception as e:
            print(f"    ❌ {ROSU}[Eroare]{RESET} Imposibil de citit {nume}: {str(e)[:60]}")

    # 4. Actualizare nomenclatoare locale (unice, sortate alfabetic)
    salveaza_lista_simpla(cale_emitenti, "Emitent", set_emitenti)
    salveaza_lista_simpla(cale_acte, "Tip_Act", set_acte)

    print(f"\n🏁 {VERDE}Nomenclatoarele din [{cale_emitenti}] și [{cale_acte}] au fost aduse la zi!{RESET}")


if __name__ == "__main__":
    proceseaza_segment_xml()
