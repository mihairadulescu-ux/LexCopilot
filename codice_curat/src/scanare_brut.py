import os
import json
import re
import csv
import io
from collections import Counter
import xml.etree.ElementTree as ET
from google.oauth2 import service_account
from googleapiclient.discovery import build
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
    return re.sub(r'\s+', ' ', text).strip()

def extrage_metadate_din_xml(xml_content):
    """Extrage emitentul și tipul actului din XML-ul brut."""
    try:
        root = ET.fromstring(xml_content)
        namespaces = {
            'a': 'http://schemas.datacontract.org/2004/07/Legis.Sg.Doc'
        }
        
        emitent_elem = root.find(".//a:Emitent", namespaces) or root.find(".//Emitent")
        tip_act_elem = root.find(".//a:TipAct", namespaces) or root.find(".//TipAct")
        
        emitent = curata_text(emitent_elem.text) if emitent_elem is not None else None
        tip_act = curata_text(tip_act_elem.text) if tip_act_elem is not None else None
        
        return emitent, tip_act
    except Exception as e:
        return None, None

def descarca_si_scaneaza_xmluri(service):
    """Căutare simplă și plată, bazată pe numele fișierului."""
    emitenti_counter = Counter()
    tipuri_acte_counter = Counter()
    
    # Folosim o căutare flexibilă după extensia .xml în loc de mimeType strict
    query = f"'{FOLDER_SURSA_ID}' in parents and name contains '.xml' and trashed = false"
    
    print("Începe căutarea fișierelor .xml direct în folder...")
    
    toate_xmlurile = []
    page_token = None
    
    while True:
        try:
            results = service.files().list(
                q=query, 
                fields="nextPageToken, files(id, name)", 
                pageSize=1000,
                pageToken=page_token
            ).execute()
            
            toate_xmlurile.extend(results.get("files", []))
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            print(f"Eroare la listarea fișierelor: {e}")
            break
            
    if not toate_xmlurile:
        print("Nu s-au găsit fișiere care să conțină '.xml' în nume direct în folderul sursă.")
        return emitenti_counter, tipuri_acte_counter

    print(f"Am găsit {len(toate_xmlurile)} fișiere XML. Începe scanarea lor...")
    
    for idx, file in enumerate(toate_xmlurile, 1):
        file_id = file["id"]
        file_name = file["name"]
        
        try:
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
                print(f"Progres scanare: {idx}/{len(toate_xmlurile)} fișiere procesate...")
                
        except Exception as e:
            print(f"Eroare la procesarea fișierului {file_name}: {e}")
            
    return emitenti_counter, tipuri_acte_counter

def salveaza_csv_in_drive(service, nume_fisier, date, antet):
    """Salvează sau suprascrie CSV-ul generat direct în folderul /Metadate."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(antet)
    for element, count in date.most_common():
        writer.writerow([element, count])
    
    csv_data = output.getvalue().encode('utf-8')
    output.close()
    
    query = f"'{FOLDER_METADATE_ID}' in parents and name = '{nume_fisier}' and trashed = false"
    existing_files = service.files().list(q=query, fields="files(id)").execute().get("files", [])
    
    media = MediaIoBaseUpload(
        io.BytesIO(csv_data), 
        mimetype="text/csv", 
        resumable=True
    )
    
    if existing_files:
        file_id = existing_files[0]["id"]
        service.files().update(fileId=file_id, media_body=media).execute()
        print(f"Fișierul {nume_fisier} a fost actualizat cu succes în folderul /Metadate.")
    else:
        metadata = {
            "name": nume_fisier,
            "parents": [FOLDER_METADATE_ID]
        }
        service.files().create(body=metadata, media_body=media).execute()
        print(f"Fișierul nou {nume_fisier} a fost creat cu succes în folderul /Metadate.")

def main():
    try:
        service = obtine_serviciu_drive()
        emitenti, tipuri_acte = descarca_si_scaneaza_xmluri(service)
        
        if emitenti or tipuri_acte:
            salveaza_csv_in_drive(service, "emitenti_brut.csv", emitenti, ["Emitent_Original", "Aparitii"])
            salveaza_csv_in_drive(service, "tipuri_acte_brut.csv", tipuri_acte, ["TipAct_Original", "Aparitii"])
            print("Procesul s-a încheiat cu succes!")
        else:
            print("Nu s-au putut colecta metadate. Asigură-te că fișierele din folder au extensia '.xml'.")
    except Exception as e:
        print(f"A apărut o eroare critică în timpul execuției: {e}")

if __name__ == "__main__":
    main()
