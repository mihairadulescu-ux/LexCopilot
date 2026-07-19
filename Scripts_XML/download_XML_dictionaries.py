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
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

# CONFIGURĂRI DIRECȚIONATE DIN MEDIU
DRIVE_FOLDER_XML = os.getenv("DRIVE_FOLDER_XML")      # Folderul mare cu XML-urile brute
METADATA_FOLDER_ID = os.getenv("METADATA_FOLDER_ID")  # Folderul unde salvăm CSV-urile finale


def get_drive_service():
    """Autentifică robotul în Google Drive folosind GitHub Secrets."""
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


def descarca_si_incarca_dictionare_existente(service):
    """Descarcă CSV-urile actuale din Drive (dacă există) ca să nu pierdem istoricul deja colectat."""
    emitenti = {}
    tip_acte = {}
    
    for nume_fisier, dictionar in [("dictionar_emitenti.csv", emitenti), ("dictionar_tip_acte.csv", tip_acte)]:
        query = f"'{METADATA_FOLDER_ID}' in parents and name = '{nume_fisier}' and trashed = false"
        files = service.files().list(q=query, spaces='drive', fields='files(id)').execute().get('files', [])
        
        if files:
            try:
                request = service.files().get_media(fileId=files[0]['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                
                fh.seek(0)
                reader = csv.reader(io.StringIO(fh.getvalue().decode('utf-8')), delimiter=";")
                next(reader, None) # Sărim headerul
                
                for rand in reader:
                    if len(rand) >= 2:
                        dictionar[rand[0]] = rand[1]
            except Exception as e:
                print(f"{GALBEN}⚠️ Nu s-a putut citi istoricul pentru {nume_fisier}, începem curat: {e}{RESET}")
                
    return emitenti, tip_acte


def salveaza_dictionare_in_drive(service, emitenti, tip_acte):
    """Scrie seturile agregate înapoi în folderul de metadate ca CSV-uri."""
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
        existing = service.files().list(q=query, spaces='drive', fields='files(id)').execute().get('files', [])
        
        media = MediaInMemoryUpload(content_bytes, mimetype="text/csv", resumable=True)
        if existing:
            service.files().update(fileId=existing[0]['id'], media_body=media).execute()
        else:
            meta = {"name": nume_fisier, "parents": [METADATA_FOLDER_ID]}
            service.files().create(body=meta, media_body=media).execute()


def proceseaza_xml_brut():
    print(f"{VERDE}🚀 Inițiere scanare matriceală XML pentru extragere metadate (Emitenți & Tip Acte)...{RESET}")
    
    if not DRIVE_FOLDER_XML or not METADATA_FOLDER_ID:
        print(f"{ROSU}🛑 Erori configurare: DRIVE_FOLDER_XML sau METADATA_FOLDER_ID lipsesc!{RESET}")
        return

    service = get_drive_service()
    
    # Pasul 1: Încărcăm în memorie ce aveam deja extras ca să nu pierdem progresul
    emitenti, tip_acte = descarca_si_incarca_dictionare_existente(service)
    print(f"📊 Bază inițială încărcată: {len(emitenti)} emitenți cunoscuți, {len(tip_acte)} tipuri de acte.")

    # Pasul 2: Căutăm fișiere XML din folderul sursă care NU au descrierea "processed_for_tags: true"
    # Interogăm fără limită de ani!
    query = f"'{DRIVE_FOLDER_XML}' in parents and name contains '.xml' and description != 'processed_for_tags: true' and trashed = false"
    
    page_token = None
    fisiere_de_procesat = []
    
    print(f"🔍 Identificăm fișiere XML noi sau neprocesate...")
    while True:
        response = service.files().list(
            q=query, spaces='drive', fields='nextPageToken, files(id, name)',
            pageToken=page_token, pageSize=500, supportsAllDrives=True, includeItemsFromAllDrives=True
        ).execute()
        
        fisiere_de_procesat.extend(response.get('files', []))
        page_token = response.get('nextPageToken', None)
        if not page_token or len(fisiere_de_procesat) >= 1500: # Procesăm în tranșe controlate per rulare
            break

    if not fisiere_de_procesat:
        print(f"{VERDE}🎉 Toate XML-urile din Drive au fost deja procesate! Dicționarele sunt la zi.{RESET}")
        return

    print(f"🧠 Am găsit {len(fisiere_de_procesat)} XML-uri noi. Începem parsarea de taguri...")
    
    modificari_detectate = False
    
    for idx, fisier in enumerate(fisiere_de_procesat, 1):
        f_id = fisier['id']
        f_nume = fisier['name']
        
        try:
            # Descărcăm conținutul XML direct în memorie (fără fișiere locale pe disc)
            request = service.files().get_media(fileId=f_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            
            xml_content = fh.getvalue()
            
            # Parsare eficientă prin stream lxml (consumă memorie minimă)
            context = etree.iterparse(io.BytesIO(xml_content), events=('end',), tag=('Emitent', 'TipAct'))
            
            for event, elem in context:
                # Căutăm structurile din nodul curent
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
                
                elem.clear() # Eliberăm nodul din RAM imediat
            
            # Pasul 3: Marcăm fișierul ca PROCESAT în metadatele Drive ca să nu-l mai citim niciodată
            service.files().update(fileId=f_id, body={'description': 'processed_for_tags: true'}).execute()
            
            if idx % 100 == 0 or idx == len(fisiere_de_procesat):
                print(f"   ↳ [{idx}/{len(fisiere_de_procesat)}] Parsat și marcat ca procesat: {f_nume}")
                
        except Exception as e:
            print(f"{ROSU}⚠️ Eroare la citirea tagurilor din {f_nume}: {e}{RESET}")
            continue

    # Pasul 4: Salvăm noile dicționare agregate înapoi în folderul de metadate
    if modificari_detectate:
        print(f"\n💾 S-au găsit taguri noi! Salvăm dicționarele actualizate...")
        salveaza_dictionare_in_drive(service, emitenti, tip_acte)
    
    print(f"{VERDE}🎉 Finalizat! Total curent în dicționare: {len(emitenti)} emitenți și {len(tip_acte)} tipuri acte.{RESET}")


if __name__ == "__main__":
    proceseaza_xml_brut()
