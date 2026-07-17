import os
import sys
import json
import csv
import io
import re
from lxml import etree
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Preluare variabile de mediu (Aliniate cu GitHub Variables)
SOURCE_XML_FOLDER_ID = os.getenv("DRIVE_FOLDER_XML")
METADATA_FOLDER_ID = os.getenv("METADATA_FOLDER_ID")

def obtine_drive():
    print("🔑 Conectare Google Drive API...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_xml_uri_drive(service):
    print(f"🔍 Căutare fișiere XML brute în folderul dedicat XML (ID: {SOURCE_XML_FOLDER_ID})...")
    xml_uri = []
    page_token = None
    query = f"'{SOURCE_XML_FOLDER_ID}' in parents and name contains 'brut_legislatie_' and name contains '.xml' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query, fields="nextPageToken, files(id, name)", pageToken=page_token, pageSize=1000,
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
        ).execute()
        xml_uri.extend(response.get("files", []))
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
    xml_uri.sort(key=lambda x: x["name"])
    print(f"📊 S-au găsit {len(xml_uri)} fișiere XML de analizat.")
    return xml_uri

def descarca_continut_xml(service, file_id):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue()

def salveaza_csv_unic_in_drive(service, nume_fisier, fieldname, set_date):
    cale_temp = f"temp_{nume_fisier}"
    # Sortăm elementele pentru o listă ordonată estetic și curat
    randuri_ordonate = sorted(list(set_date))
    
    print(f"✍️ Scrierea listei unice: {nume_fisier} ({len(randuri_ordonate)} valori distincte)...")
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([fieldname])  # Header-ul coloanei
        for valoare in randuri_ordonate:
            writer.writerow([valoare])
        
    query = f"'{METADATA_FOLDER_ID}' in parents and name = '{nume_fisier}' and trashed = false"
    existente = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
    ).execute().get("files", [])
    
    media = MediaFileUpload(cale_temp, mimetype="text/csv", resumable=True)
    if existente:
        file_id = existente[0]["id"]
        service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        print(f"💾 [UPDATE] Catalog unic salvat: {nume_fisier} -> ID: {file_id}")
    else:
        metadata = {'name': nume_fisier, 'parents': [METADATA_FOLDER_ID]}
        nou = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
        print(f"🆕 [CREATE] Catalog unic creat: {nume_fisier} -> ID: {nou['id']}")
    os.remove(cale_temp)

def extrage_an_si_numar_mo(nume_fisier):
    m = re.search(r"brut_legislatie_(\d{4})_pag(\d+)", nume_fisier)
    if m:
        return m.group(1), m.group(2)
    return "", ""

def parcurge_si_extrage():
    if not SOURCE_XML_FOLDER_ID or not METADATA_FOLDER_ID:
        print("❌ EROARE CRITICĂ: Variabilele de mediu DRIVE_FOLDER_XML sau METADATA_FOLDER_ID sunt incomplete!")
        sys.exit(1)
        
    service = obtine_drive()
    fisiere_xml = listeaza_xml_uri_drive(service)
    
    # Folosim structuri de tip SET pentru a asigura unicitatea absolută din fașă
    set_tipuri_acte = set()
    set_emitenti = set()
    set_numere_mo = set()
    
    count = 0
    for fx in fisiere_xml:
        count += 1
        nume_xml = fx['name']
        an_implicit, pag_implicit = extrage_an_si_numar_mo(nume_xml)
        
        print(f"⏳ [{count}/{len(fisiere_xml)}] Colectare valori unice din {nume_xml}...")
        try:
            xml_bytes = descarca_continut_xml(service, fx['id'])
            root = etree.fromstring(xml_bytes)
            
            noduri_acte = root.xpath("//act | //document | //item | //record")
            if not noduri_acte:
                noduri_acte = list(root)
                
            for nod in noduri_acte:
                mo_numar_raw = ""
                
                for copil in nod.iter():
                    tag_simplu = copil.tag.split('}')[-1].lower() if '}' in copil.tag else copil.tag.lower()
                    text = copil.text.strip() if copil.text else ""
                    
                    if not text:
                        continue
                        
                    # 1. Colectăm tipul de act direct în formatul lui brut curățat
                    if tag_simplu in ["tip", "tip_act", "tipact", "categorie"]:
                        set_tipuri_acte.add(text.upper())
                        
                    # 2. Colectăm emitentul direct
                    elif tag_simplu in ["emitent", "autor", "institutie"]:
                        set_emitenti.add(text.upper())
                        
                    # 3. Colectăm numărul de Monitor Oficial întâlnit
                    elif tag_simplu in ["mo", "mo_numar", "monitor", "monitor_oficial", "numar_mo", "publicare_nr"]:
                        mo_curat = re.search(r"\b\d+\b", text)
                        if mo_curat:
                            mo_numar_raw = mo_curat.group(0)
                
                # Fallback pe numele fișierului dacă nodul curent n-a raportat un număr de MO
                mo_final = mo_numar_raw if mo_numar_raw else pag_implicit
                if mo_final:
                    set_numere_mo.add(mo_final)
                    
        except Exception as e:
            print(f"    ⚠️ Eroare la citirea fișierului {nume_xml}: {e}")
            
    print(f"\n📊 Extracție unică terminată! Inventar nomenclature brute:")
    print(f" -> Tipuri acte unice: {len(set_tipuri_acte)}")
    print(f" -> Emitenți unici: {len(set_emitenti)}")
    print(f" -> Numere MO unice întâlnite: {len(set_numere_mo)}")
    
    # Salvarea celor 3 liste subțiri de valori distincte
    if set_tipuri_acte:
        salveaza_csv_unic_in_drive(service, "catalog_tip_acte.csv", "tip_act", set_tipuri_acte)
    if set_emitenti:
        salveaza_csv_unic_in_drive(service, "catalog_emitenti.csv", "emitent", set_emitenti)
    if set_numere_mo:
        salveaza_csv_unic_in_drive(service, "catalog_numar_mo.csv", "mo_numar", set_numere_mo)
        
    print("\n🚀 [FINALIZAT] Nomenclatoarele unice au fost salvate la dimensiuni minime în Drive!")

if __name__ == "__main__":
    parcurge_si_extrage()
