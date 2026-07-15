import os
import json
import re
import csv
import io
from collections import Counter
import xml.etree.ElementTree as ET
from google.oauth2 import service_account
from googleapiclient.discovery import build
# IMPORT CORECTAT: Am adăugat MediaIoBaseUpload pentru fluxuri în memorie
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ID-urile folderelor tale din Google Drive
FOLDER_SURSA_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
FOLDER_METADATE_ID = "1Cpxs20QAtAPw_RIUsOOecJON9hHPlBXf"

def obtine_serviciu_drive():
    """Autentificare securizată folosind cheia secretă din GitHub Actions."""
    creds_json = os.environ.get("GDRIVE_CREDENTIALS")
    if not creds_json:
        raise ValueError("Eroare: Variabila de mediu GDRIVE_CREDENTIALS lipsește din GitHub Secrets!")
    
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

def curata_text(text):
    if not text:
        return ""
    # Elimină spațiile multiple și liniile noi
    return re.sub(r'\s+', ' ', text).strip()

def extrage_metadate_din_xml(xml_content):
    """Extrage emitentul și tipul actului din XML-ul brut."""
    try:
        root = ET.fromstring(xml_content)
        # Namespace-urile comune din XML-urile tale SOAP/WCF
        namespaces = {
            'a': 'http://schemas.datacontract.org/2004/07/Legis.Sg.Doc'
        }
        
        # Căutăm cu namespace-ul specific sau direct dacă nu este prezent
        emitent_elem = root.find(".//a:Emitent", namespaces) or root.find(".//Emitent")
        tip_act_elem = root.find(".//a:TipAct", namespaces) or root.find(".//TipAct")
        
        emitent = curata_text(emitent_elem.text) if emitent_elem is not None else None
        tip_act = curata_text(tip_act_elem.text) if tip_act_elem is not None else None
        
        return emitent, tip_act
    except Exception as e:
        print(f"Eroare la parsarea structurii XML: {e}")
        return None, None

def descarca_si_scaneaza_xmluri(service):
    """Scanează recursiv folderul sursă și analizează fișierele XML."""
    emitenti_counter = Counter()
    tipuri_acte_counter = Counter()
    
    # Căutăm toate fișierele XML din folderul sursă
    query = f"'{FOLDER_SURSA_ID}' in parents and mimeType = 'text/xml' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)", pageSize=1000).execute()
    files = results.get("files", [])
    
    if not files:
        print("Nu s-au găsit fișiere XML în folderul sursă. Verifică dacă ai dat share folderului cu emailul din Service Account!")
        return emitenti_counter, tipuri_acte_counter

    print(f"Am găsit {len(files)} fișiere XML. Începe scanarea...")
    
    for idx, file in enumerate(files, 1):
        file_id = file["id"]
        file_name = file["name"]
        
        try:
            # Descărcare în memorie (fără a scrie pe disk)
            request = service.files().get_media(fileId=file_id)
            file_buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(file_buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            
            xml_content = file_buffer.getvalue()
            emitent, tip_act = extrage_metadate_din_xml(xml_content)
            
            if emitent:
                emitenti_counter[emitent] += 1
            if tip_act:
                tipuri_acte_counter[tip_act] += 1
                
            if idx % 50 == 0:
                print(f"Progres: {idx}/{len(files)} fișiere procesate...")
                
        except Exception as e:
            print(f"Eroare la procesarea fișierului {file_name}: {e}")
            
    return emitenti_counter, tipuri_acte_counter

def salveaza_csv_in_drive(service, nume_fisier, date, antet):
    """Generează CSV-ul local și îl uploadează direct în folderul /Metadate."""
    # 1. Generare CSV în memorie
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(antet)
    for element, count in date.most_common():
        writer.writerow([element, count])
    
    csv_data = output.getvalue().encode('utf-8')
    output.close()
    
    # 2. Verificăm dacă fișierul există deja în folderul destinație ca să îl suprascriem (update)
    query = f"'{FOLDER_METADATE_ID}' in parents and name = '{nume_fisier}' and trashed = false"
    existing_files = service.files().list(q=query, fields="files(id)").execute().get("files", [])
    
    # REPARAT: Folosim MediaIoBaseUpload în loc de MediaFileUpload pentru fișiere virtuale
    media = MediaIoBaseUpload(
        io.BytesIO(csv_data), 
        mimetype="text/csv", 
        resumable=True
    )
    
    if existing_files:
        # Suprascriem fișierul existent
        file_id = existing_files[0]["id"]
        service.files().update(fileId=file_id, media_body=media).execute()
        print(f"Fișierul {nume_fisier} a fost actualizat cu succes în Google Drive.")
    else:
        # Cream un fișier nou
        metadata = {
            "name": nume_fisier,
            "parents": [FOLDER_METADATE_ID]
        }
        service.files().create(body=metadata, media_body=media).execute()
        print(f"Fișierul nou {nume_fisier} a fost creat cu succes în Google Drive.")

def main():
    try:
        service = obtine_serviciu_drive()
        emitenti, tipuri_acte = descarca_si_scaneaza_xmluri(service)
        
        # Dacă am găsit date relevante, le exportăm
        if emitenti or tipuri_acte:
            salveaza_csv_in_drive(service, "emitenti_brut.csv", emitenti, ["Emitent_Original", "Aparitii"])
            salveaza_csv_in_drive(service, "tipuri_acte_brut.csv", tipuri_acte, ["TipAct_Original", "Aparitii"])
            print("Procesul s-a încheiat cu succes! Fișierele sunt gata pentru normalizare.")
        else:
            print("Nu s-a generat niciun raport deoarece nu au putut fi citite XML-uri.")
    except Exception as e:
        print(f"A apărut o eroare critică în timpul execuției: {e}")

if __name__ == "__main__":
    main()
