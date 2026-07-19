# Culori pentru un log frumos în consolă
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

import os
import io
import csv
import json
from lxml import etree
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

# Citim variabila care poate conține mai multe ID-uri separate prin virgulă
TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")
METADATA_FOLDER_ID = os.getenv("METADATA_FOLDER_ID")  

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipsește secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def descarca_si_incarca_dictionare_existente(service):
    emitenti = {}
    tip_acte = {}
    for nume_fisier, dictionar in [("dictionar_emitenti.csv", emitenti), ("dictionar_tip_acte.csv", tip_acte)]:
        query = f"'{METADATA_FOLDER_ID}' in parents and name = '{nume_fisier}' and trashed = false"
        try:
            files = service.files().list(
                q=query, 
                spaces='drive', 
                fields='files(id)', 
                supportsAllDrives=True, 
                includeItemsFromAllDrives=True
            ).execute().get('files', [])
            
            if files:
                request = service.files().get_media(fileId=files[0]['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                fh.seek(0)
                reader = csv.reader(io.StringIO(fh.getvalue().decode('utf-8')), delimiter=";")
                next(reader, None)
                for rand in reader:
                    if len(rand) >= 2:
                        dictionar[rand[0]] = rand[1]
        except Exception as e:
            print(f"{GALBEN}⚠️ Nu s-a putut citi istoricul pentru {nume_fisier}: {e}{RESET}")
    return emitenti, tip_acte

def salveaza_dictionare_in_drive(service, emitenti, tip_acte):
    for nume_fisier, date, header in [
        ("dictionar_emitenti.csv", emitenti, ["ID", "Denumire"]),
        ("dictionar_tip_acte.csv", tip_acte, ["ID", "Denumire"])
    ]:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(header)
        for k, v in sorted(date.items()):
            writer.writerow([k, v])
        content_bytes = output.getvalue().encode('utf-8')
        query = f"'{METADATA_FOLDER_ID}' in parents and name = '{nume_fisier}' and trashed = false"
        
        try:
            existing = service.files().list(
                q=query, 
                spaces='drive', 
                fields='files(id)', 
                supportsAllDrives=True, 
                includeItemsFromAllDrives=True
            ).execute().get('files', [])
            
            media = MediaInMemoryUpload(content_bytes, mimetype="text/csv", resumable=True)
            if existing:
                service.files().update(fileId=existing[0]['id'], media_body=media, supportsAllDrives=True).execute()
            else:
                meta = {"name": nume_fisier, "parents": [METADATA_FOLDER_ID]}
                service.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
        except Exception as e:
            print(f"{ROSU}❌ Eroare salvare dicționar {nume_fisier}: {e}{RESET}")

def proceseaza_xml_brut():
    print(f"{VERDE}🚀 Inițiere scanare matriceală XML pentru extragere metadate...{RESET}")
    if not TARGET_FOLDERS_RAW or not METADATA_FOLDER_ID:
        print(f"{ROSU}🛑 Erori configurare: DRIVE_FOLDER_XML sau METADATA_FOLDER_ID lipsesc!{RESET}")
        return

    # Extragem lista de ID-uri din variabila globală
    folder_ids = [fid.strip() for fid in TARGET_FOLDERS_RAW.split(",") if fid.strip()]
    
    service = obtine_drive()
    emitenti, tip_acte = descarca_si_incarca_dictionare_existente(service)
    print(f"📊 Bază inițială încărcată: {len(emitenti)} emitenți cunoscuți, {len(tip_acte)} tipuri de acte.")

    toate_fisierele = []
    print(f"🔍 Identificăm fișiere din cele {len(folder_ids)} locații mapate...")
    
    # Parcurgem fiecare Shared Drive definit
    for folder_id in folder_ids:
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"
        
        while True:
            try:
                # Încercare standard pe bază de structură ierarhică
                response = service.files().list(
                    q=query, 
                    spaces='drive', 
                    fields='nextPageToken, files(id, name, description)',
                    pageToken=page_token, 
                    pageSize=1000, 
                    supportsAllDrives=True, 
                    includeItemsFromAllDrives=True
                ).execute()
                toate_fisierele.extend(response.get('files', []))
                page_token = response.get('nextPageToken', None)
                if not page_token:
                    break
            except Exception:
                # PLANUL B: Dacă dă 404, facem căutarea imună la structura folderului rădăcină
                try:
                    query_alt = "name contains '.xml' and trashed = false"
                    response_alt = service.files().list(
                        q=query_alt,
                        spaces='drive',
                        fields='nextPageToken, files(id, name, description)',
                        pageToken=page_token,
                        pageSize=1000,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True
                    ).execute()
                    toate_fisierele.extend(response_alt.get('files', []))
                    page_token = response_alt.get('nextPageToken', None)
                    if not page_token:
                        break
                except Exception as e_alt:
                    print(f"{ROSU}⚠️ Nu s-a putut scana locația {folder_id}: {e_alt}{RESET}")
                    break

    # Filtrare locală Python: extragem STRICT XML-urile care sunt neprocesate
    fisiere_de_procesat = [
        f for f in toate_fisierele 
        if f.get('name', '').lower().endswith('.xml') and f.get('description') != 'processed_for_tags: true'
    ][:1500] 

    if not fisiere_de_procesat:
        print(f"{VERDE}🎉 Toate XML-urile din Shared Drives au fost deja procesate! Dicționarele sunt la zi.{RESET}")
        return

    print(f"🧠 Am găsit {len(fisiere_de_procesat)} XML-uri UNPROCESSED. Începem parsarea de taguri...")
    modificari_detectate = False
    
    for idx, fisier in enumerate(fisiere_de_procesat, 1):
        f_id = fisier['id']
        f_nume = fisier['name']
        try:
            request = service.files().get_media(fileId=f_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            
            xml_content = fh.getvalue()
            context = etree.iterparse(io.BytesIO(xml_content), events=('end',), tag=('Emitent', 'TipAct'))
            
            for event, elem in context:
                if elem.tag == 'Emitent':
                    id_em = elem.findtext('Id') or elem.findtext('{http://schemas.datacontract.org/2004/07/FreeWebService}Id')
                    nume_em = elem.findtext('Denumire') or elem.findtext('{http://schemas.datacontract.org/2004/07/FreeWebService}Denumire')
                    if id_em and nume_em and id_em not in emitenti:
                        emitenti[id_em] = nume_em.strip()
                        modificari_detectate = True
                elif elem.tag == 'TipAct':
                    id_tip = elem.findtext('Id') or elem.findtext('{http://schemas.datacontract.org/2004/07/FreeWebService}Id')
                    nume_tip = elem.findtext('Denumire') or elem.findtext('{http://schemas.datacontract.org/2004/07/FreeWebService}Denumire')
                    if id_tip and nume_tip and id_tip not in tip_acte:
                        tip_acte[id_tip] = nume_tip.strip()
                        modificari_detectate = True
                elem.clear()
            
            # Marcăm fișierul ca procesat direct în metadate
            service.files().update(fileId=f_id, body={'description': 'processed_for_tags: true'}, supportsAllDrives=True).execute()
            if idx % 100 == 0 or idx == len(fisiere_de_procesat):
                print(f"   ↳ [{idx}/{len(fisiere_de_procesat)}] Parsat și marcat: {f_nume}")
        except Exception as e:
            print(f"{ROSU}⚠️ Eroare la citirea tagurilor din {f_nume}: {e}{RESET}")
            continue

    if modificari_detectate:
        print(f"\n💾 S-au găsit taguri noi! Salvăm dicționarele în folderul de metadate...")
        salveaza_dictionare_in_drive(service, emitenti, tip_acte)
        
    print(f"{VERDE}🎉 Finalizat! Total curent: {len(emitenti)} emitenți și {len(tip_acte)} tipuri acte.{RESET}")

if __name__ == "__main__":
    proceseaza_xml_brut()
