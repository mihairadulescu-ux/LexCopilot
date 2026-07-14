import os
import re
import io
import json
import unicodedata
from bs4 import BeautifulSoup

# Google API client imports
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ID-urile de Google Drive furnizate de tine
ID_FOLDER_SURSA = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
ID_FOLDER_DESTINATIE = "1QWfGTI5BoybtHjPIL5yAeZNp5b4nSeg1"

# Domeniul de permisiuni necesar pentru Google Drive
SCOPES = ['https://www.googleapis.com/auth/drive']

def obtine_serviciu_drive():
    """Realizează autentificarea folosind cheia secretă din variabilele de mediu."""
    creds_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    
    if not creds_json_str:
        raise ValueError(
            "Eroare: Nu am găsit variabila de mediu GOOGLE_CREDENTIALS_JSON! "
            "Asigură-te că ai configurat corect cheia în GitHub Secrets sau în mediu."
        )
        
    try:
        creds_info = json.loads(creds_json_str)
    except Exception as e:
        raise ValueError(f"Eroare la parsarea JSON-ului din GOOGLE_CREDENTIALS_JSON: {str(e)}")
    
    # Ne autentificăm folosind Service Account-ul configurat în secrete
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES
    )
    
    return build('drive', 'v3', credentials=creds)

def curata_text(text):
    """Elimină diacriticele și caracterele speciale pentru denumiri sigure."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[^a-zA-Z0-9_\s-]', '', text).strip()

def obtine_acronim_emitent(emitent_raw):
    """Scurtează numele emitentului pentru numele fișierului."""
    if not emitent_raw:
        return "AUT"
    
    emitent_curat = curata_text(emitent_raw).upper()
    mapari_standard = {
        "PRESEDINTELE ROMANIEI": "PRES",
        "CURTEA CONSTITUTIONALA": "CCR",
        "MINISTERUL SANATATII": "MS",
        "MINISTERUL AFACERILOR INTERNE": "MAI",
        "MINISTERUL JUSTITIEI": "MJ",
        "GUVERNUL ROMANIEI": "GUV",
        "PARLAMENTUL ROMANIEI": "PARL",
        "SENATUL ROMANIEI": "SENAT",
        "CAMERA DEPUTATILOR": "CAMERA",
        "PRIM-MINISTRU": "PM"
    }
    
    if emitent_curat in mapari_standard:
        return mapari_standard[emitent_curat]
    
    cuvinte = [w for w in emitent_curat.split() if w not in ["DE", "AL", "PENTRU", "SI", "CONSTR"]]
    if len(cuvinte) >= 2:
        return "_".join([w[:3] for w in cuvinte[:3]])
    
    return emitent_curat[:10].replace(" ", "_")

def extrage_referinta_mo(titlu, continut):
    """Identifică referința Monitorului Oficial."""
    pattern = re.compile(
        r'(Monitorul\s+Oficial|M\.\s*Of\.)\s*(al\s+României\s*)?(Partea\s+I\s+)?(nr\.|nr|/)\s*([0-9\s\.\-/a-zA-Z]+din\s+[0-9]+\s+[a-zA-Z]+\s+[0-9]{4}|[0-9]+/[0-9]{4}|[0-9]+)',
        re.IGNORECASE
    )
    
    match = pattern.search(titlu)
    if match:
        return match.group(0).strip()
    
    match = pattern.search(continut[:1500])
    if match:
        return match.group(0).strip()
    
    return "Nespecificat"

def obtine_sau_creeaza_folder_drive(service, nume_folder, parinte_id):
    """Verifică dacă un subfolder există în Google Drive, dacă nu, îl creează."""
    query = f"name = '{nume_folder}' and '{parinte_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    rezultate = service.files().list(q=query, fields="files(id)").execute()
    fisiere = rezultate.get('files', [])
    
    if fisiere:
        return fisiere[0]['id']
    
    # Dacă nu există, îl creăm
    metadate_folder = {
        'name': nume_folder,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parinte_id]
    }
    folder_nou = service.files().create(body=metadate_folder, fields='id').execute()
    print(f" -> Creat folder nou în Drive: {nume_folder}")
    return folder_nou['id']

def proceseaza_si_salveaza_in_drive(service, file_id, file_name):
    """Descarcă un XML brut din Drive, îl procesează și îl salvează structurat în destinație."""
    print(f"\nSe descarcă pentru procesare: {file_name}")
    
    # 1. Descarcă fișierul din Drive în memorie
    request = service.files().get_media(fileId=file_id)
    file_buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(file_buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        
    raw_data = file_buffer.getvalue().decode('utf-8', errors='replace')
    
    # 2. Parsare conținut cu BeautifulSoup
    soup = BeautifulSoup(raw_data, "xml")
    documente = soup.find_all("Document") or soup.find_all("document")
    
    print(f" -> Am găsit {len(documente)} acte în acest fișier.")
    
    for doc in documente:
        id_intern = doc.find("id").text.strip() if doc.find("id") else "FARA_ID"
        tip_act_raw = doc.find("tip_act").text.strip() if doc.find("tip_act") else "ACT"
        numar = doc.find("numar").text.strip() if doc.find("numar") else "FARA_NUMAR"
        an = doc.find("an").text.strip() if doc.find("an") else "FARA_AN"
        data_pub = doc.find("data").text.strip() if doc.find("data") else ""
        titlu = doc.find("titlu").text.strip() if doc.find("titlu") else ""
        emitent_raw = doc.find("emitent").text.strip() if doc.find("emitent") else ""
        
        continut_raw = doc.find("continut").text if doc.find("continut") else ""
        continut_text_curat = BeautifulSoup(continut_raw, "html.parser").get_text(separator=" ")
        
        referinta_mo = extrage_referinta_mo(titlu, continut_text_curat)
        
        # Generare denumiri curate
        emitent_folder_name = curata_text(emitent_raw).upper().replace(" ", "_") or "AUTORITATE_NESPECIFICATA"
        emitent_acronim = obtine_acronim_emitent(emitent_raw)
        
        # 3. Navigare / Creare structură ierarhică în Google Drive: EMITENT / AN
        id_folder_emitent = obtine_sau_creeaza_folder_drive(service, emitent_folder_name, ID_FOLDER_DESTINATIE)
        id_folder_an = obtine_sau_creeaza_folder_drive(service, an, id_folder_emitent)
        
        # 4. Generare XML nou, curat
        xml_nou = BeautifulSoup(features="xml")
        root_tag = xml_nou.new_tag("ActJuridic")
        xml_nou.append(root_tag)
        
        tags_de_adaugat = {
            "referinta_mo": referinta_mo,
            "tip_act": tip_act_raw.upper(),
            "numar": numar,
            "an": an,
            "data_publicare": data_pub,
            "emitent": emitent_raw,
            "titlu": titlu,
            "id_original": id_intern
        }
        
        for nume_tag, valoare in tags_de_adaugat.items():
            nou_tag = xml_nou.new_tag(nume_tag)
            nou_tag.string = valoare
            root_tag.append(nou_tag)
            
        continut_tag = xml_nou.new_tag("continut")
        continut_tag.string = continut_raw
        root_tag.append(continut_tag)
        
        # Nume fișier final
        tip_act_curat = curata_text(tip_act_raw).upper().replace(" ", "_")
        nume_fisier_nou = f"{tip_act_curat}_{emitent_acronim}_{numar}_{an}.xml"
        
        # 5. Upload direct în subfolderul corespunzător din Drive
        xml_bytes = xml_nou.prettify().encode('utf-8')
        media_body = MediaIoBaseUpload(io.BytesIO(xml_bytes), mimetype='text/xml', resumable=True)
        
        metadate_fisier = {
            'name': nume_fisier_nou,
            'parents': [id_folder_an]
        }
        
        # Verificăm dacă fișierul există deja în acea locație pentru a nu face duplicat gratuit
        query_dublura = f"name = '{nume_fisier_nou}' and '{id_folder_an}' in parents and trashed = false"
        rezultate_dublura = service.files().list(q=query_dublura, fields="files(id)").execute()
        fisiere_existente = rezultate_dublura.get('files', [])
        
        if fisiere_existente:
            # Update (suprascriere) dacă există deja
            id_existent = fisiere_existente[0]['id']
            service.files().update(fileId=id_existent, media_body=media_body).execute()
            print(f" -> [UPDATE] {nume_fisier_nou} a fost actualizat.")
        else:
            # Create nou
            service.files().create(body=metadate_fisier, media_body=media_body).execute()
            print(f" -> [CREAT] {nume_fisier_nou} salvat cu succes.")

def main():
    try:
        service = obtine_serviciu_drive()
        
        # Scanăm folderul sursă după toate fișierele XML
        query_sursa = f"'{ID_FOLDER_SURSA}' in parents and mimeType = 'text/xml' and trashed = false"
        rezultate = service.files().list(q=query_sursa, fields="files(id, name)").execute()
        fisiere_xml = rezultate.get('files', [])
        
        if not fisiere_xml:
            # Încercăm o căutare mai permisivă în caz că mimeType diferă la upload
            query_sursa_permisiv = f"'{ID_FOLDER_SURSA}' in parents and name contains '.xml' and trashed = false"
            rezultate = service.files().list(q=query_sursa_permisiv, fields="files(id, name)").execute()
            fisiere_xml = rezultate.get('files', [])
            
        print(f"Am găsit {len(fisiere_xml)} fișiere XML brute în folderul sursă Google Drive.")
        
        for f in fisiere_xml:
            proceseaza_si_salveaza_in_drive(service, f['id'], f['name'])
            
        print("\n=== Rularea s-a încheiat cu succes! Toate documentele de test au fost procesate. ===")
        
    except Exception as e:
        print(f"A apărut o eroare critică în timpul execuției: {str(e)}")

if __name__ == "__main__":
    main()