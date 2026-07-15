import os
import json
import re
import csv
import io
import time
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
    """
    Extrage emitentul și tipul actului din XML-ul brut.
    Folosește o metodă imună la namespace-uri (caută tag-uri care se termină în 'Emitent' sau 'TipAct').
    """
    try:
        root = ET.fromstring(xml_content)
        
        emitent = None
        tip_act = None
        
        # Iterăm prin toate elementele din XML și căutăm potriviri ignorând namespace-ul
        for elem in root.iter():
            # În ElementTree, tag-ul complet arată ca "{http://namespace}NumeTag" sau simplu "NumeTag"
            # extragem doar partea de după acoladă (numele local al tag-ului)
            local_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            if local_name == "Emitent" and elem.text:
                emitent = curata_text(elem.text)
            elif local_name == "TipAct" and elem.text:
                tip_act = curata_text(elem.text)
                
            # Dacă le-am găsit pe amândouă, ne putem opri mai devreme
            if emitent and tip_act:
                break
                
        return emitent, tip_act
    except Exception as e:
        # Returnăm None în caz de eroare de parsare, dar lăsăm scriptul să meargă mai departe
        return None, None

def descarca_si_scaneaza_xmluri(service):
    """Listare și scanare cu status update detaliat și progres în consolă."""
    emitenti_counter = Counter()
    tipuri_acte_counter = Counter()
    
    query = f"'{FOLDER_SURSA_ID}' in parents and trashed = false"
    
    print(f"[{time.strftime('%H:%M:%S')}] Pasul 1: Interogare fișiere din folderul sursă...")
    
    toate_fisierele = []
    page_token = None
    
    while True:
        try:
            results = service.files().list(
                q=query, 
                fields="nextPageToken, files(id, name, mimeType)", 
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            toate_fisierele.extend(results.get("files", []))
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            print(f"Eroare critică la listarea fișierelor: {e}")
            break

    if not toate_fisierele:
        print("\n!!! API-ul Google Drive a returnat 0 fișiere.")
        return emitenti_counter, tipuri_acte_counter

    toate_xmlurile = [f for f in toate_fisierele if f['name'].lower().endswith('.xml')]
    total_xmluri = len(toate_xmlurile)
    
    print(f"[{time.strftime('%H:%M:%S')}] Pasul 2: S-au detectat în total {len(toate_fisierele)} elemente.")
    print(f" -> Dintre acestea, {total_xmluri} sunt fișiere XML valide.")
    
    if total_xmluri == 0:
        print("Nu s-au găsit XML-uri de procesat.")
        return emitenti_counter, tipuri_acte_counter

    print(f"\n[{time.strftime('%H:%M:%S')}] Pasul 3: Începe descărcarea și procesarea în timp real...\n")
    
    start_time = time.time()
    
    for idx, file in enumerate(toate_xmlurile, 1):
        file_id = file["id"]
        file_name = file["name"]
        
        try:
            # Afișăm în consolă fișierul curent
            print(f"[{idx}/{total_xmluri}] Se procesează: {file_name}...", end="\r", flush=True)
            
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
                
            # Din 100 în 100 de fișiere, afișăm un status intermediar complet
            if idx % 100 == 0:
                elapsed = time.time() - start_time
                viteza = idx / elapsed if elapsed > 0 else 0
                estimat_ramas = (total_xmluri - idx) / viteza if viteza > 0 else 0
                
                print(f"\n--- [Status intermediar {idx}/{total_xmluri}] ---")
                print(f"  > Timp scurs: {int(elapsed)}s | Rămase aproximative: {int(estimat_ramas)}s")
                print(f"  > Viteza de procesare: {viteza:.2f} fișiere/secundă")
                print(f"  > Emitenți unici detectați până acum: {len(emitenti_counter)}")
                print(f"  > Tipuri de acte unice detectate până acum: {len(tipuri_acte_counter)}")
                # Afișăm top 3 din fiecare pentru confirmare vizuală rapidă
                if emitenti_counter:
                    print(f"  > Exemple emitenți: {dict(emitenti_counter.most_common(3))}")
                if tipuri_acte_counter:
                    print(f"  > Exemple tipuri: {dict(tipuri_acte_counter.most_common(3))}")
                print("------------------------------------------\n")
                
        except Exception as e:
            print(f"\n[Eroare] Eșec la procesarea fișierului {file_name}: {e}")
            
    total_time = time.time() - start_time
    print(f"\n\n[{time.strftime('%H:%M:%S')}] Scanarea a fost finalizată în {total_time:.2f} secunde.")
    print(f" -> Total fișiere scanate cu succes: {idx}")
    
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
    
    existing_files = service.files().list(
        q=query, 
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute().get("files", [])
    
    media = MediaIoBaseUpload(
        io.BytesIO(csv_data), 
        mimetype="text/csv", 
        resumable=True
    )
    
    if existing_files:
        file_id = existing_files[0]["id"]
        service.files().update(
            fileId=file_id, 
            media_body=media,
            supportsAllDrives=True
        ).execute()
        print(f"[{time.strftime('%H:%M:%S')}] Fișierul {nume_fisier} a fost actualizat cu succes în /Metadate.")
    else:
        metadata = {
            "name": nume_fisier,
            "parents": [FOLDER_METADATE_ID]
        }
        service.files().create(
            body=metadata, 
            media_body=media,
            supportsAllDrives=True
        ).execute()
        print(f"[{time.strftime('%H:%M:%S')}] Fișierul nou {nume_fisier} a fost creat cu succes în /Metadate.")

def main():
    try:
        service = obtine_serviciu_drive()
        emitenti, tipuri_acte = descarca_si_scaneaza_xmluri(service)
        
        if emitenti or tipuri_acte:
            salveaza_csv_in_drive(service, "emitenti_brut.csv", emitenti, ["Emitent_Original", "Aparitii"])
            salveaza_csv_in_drive(service, "tipuri_acte_brut.csv", tipuri_acte, ["TipAct_Original", "Aparitii"])
            print(f"[{time.strftime('%H:%M:%S')}] Procesul complet s-a încheiat cu succes!")
        else:
            print("Nu s-au putut colecta metadate valide din XML-urile procesate.")
    except Exception as e:
        print(f"A apărut o eroare critică în timpul execuției: {e}")

if __name__ == "__main__":
    main()
