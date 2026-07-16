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

# Citire strictă din mediu - fără rezerve!
SOURCE_XML_FOLDER_ID = os.getenv("DRIVE_FOLDER_XML")
METADATA_FOLDER_ID = os.getenv("METADATA_FOLDER_ID")

URL_TEMPLATE = "https://www.monitoruloficial.ro/emonitor/PDF_baza.php?an={an}&numar={numar}"

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

def salveaza_csv_in_drive(service, nume_fisier, fieldnames, date_rows):
    cale_temp = f"temp_{nume_fisier}"
    print(f"✍️ Scrierea temporară a celor {len(date_rows)} înregistrări...")
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(date_rows)
        
    # Verificăm existența în folderul DEDICAT de metadate
    query = f"'{METADATA_FOLDER_ID}' in parents and name = '{nume_fisier}' and trashed = false"
    existente = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
    ).execute().get("files", [])
    
    media = MediaFileUpload(cale_temp, mimetype="text/csv", resumable=True)
    if existente:
        file_id = existente[0]["id"]
        service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        print(f"💾 [UPDATE] Catalog stocat în folderul dedicat metadate: {nume_fisier} (ID: {file_id})")
    else:
        metadata = {'name': nume_fisier, 'parents': [METADATA_FOLDER_ID]}
        nou = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
        print(f"🆕 [CREATE] Catalog nou creat în folderul dedicat metadate: {nume_fisier} (ID: {nou['id']})")
    os.remove(cale_temp)

def extrage_an_si_numar_mo(nume_fisier):
    m = re.search(r"brut_legislatie_(\d{4})_pag(\d+)", nume_fisier)
    if m:
        return m.group(1), m.group(2)
    return "", ""

def parcurge_si_extrage():
    # Validare strictă a variabilelor de mediu înainte de a începe orice procesare
    if not SOURCE_XML_FOLDER_ID:
        print("❌ EROARE CRITICĂ: Variabila de mediu 'DRIVE_FOLDER_XML' nu este setată!")
        sys.exit(1)
        
    if not METADATA_FOLDER_ID:
        print("❌ EROARE CRITICĂ: Variabila de mediu 'METADATA_FOLDER_ID' nu este setată!")
        sys.exit(1)
        
    service = obtine_drive()
    fisiere_xml = listeaza_xml_uri_drive(service)
    
    catalog_acte = []
    fieldnames = ["emitent", "tip_act", "titlu_act", "numar_act", "an_act", "mo_numar", "mo_an"]
    
    count = 0
    for fx in fisiere_xml:
        count += 1
        nume_xml = fx['name']
        an_implicit, pag_implicit = extrage_an_si_numar_mo(nume_xml)
        
        print(f"⏳ [{count}/{len(fisiere_xml)}] Se procesează {nume_xml}...")
        try:
            xml_bytes = descarca_continut_xml(service, fx['id'])
            root = etree.fromstring(xml_bytes)
            
            noduri_acte = root.xpath("//act | //document | //item | //record")
            if not noduri_acte:
                noduri_acte = list(root)
                
            for nod in noduri_acte:
                act_data = {f: "" for f in fieldnames}
                
                for copil in nod.iter():
                    tag_simplu = copil.tag.split('}')[-1].lower() if '}' in copil.tag else copil.tag.lower()
                    text = copil.text.strip() if copil.text else ""
                    
                    if not text:
                        continue
                        
                    if tag_simplu in ["emitent", "autor", "institutie"]:
                        act_data["emitent"] = text.upper()
                    elif tag_simplu in ["tip", "tip_act", "categorie_act", "categorie"]:
                        act_data["tip_act"] = text.upper()
                    elif tag_simplu in ["titlu", "nume", "nume_act", "subiect"]:
                        act_data["titlu_act"] = text
                    elif tag_simplu in ["numar", "numar_act", "nr"]:
                        act_data["numar_act"] = text
                    elif tag_simplu in ["an", "an_act", "data", "data_act", "data_emitere"]:
                        an_m = re.search(r"\b(19\d{2}|20[0-2]\d)\b", text)
                        if_an_m = an_m.group(1) if_an_m := an_m else None
                        if if_an_m:
                            act_data["an_act"] = if_an_m.group(1)
                        else:
                            act_data["an_act"] = text
                    elif tag_simplu in ["mo", "mo_numar", "monitor", "monitor_oficial", "numar_mo"]:
                        act_data["mo_numar"] = text
                        
                if act_data["emitent"] or act_data["tip_act"] or act_data["titlu_act"]:
                    if not act_data["an_act"]:
                        act_data["an_act"] = an_implicit
                    else:
                        an_curat = re.search(r"\b(19\d{2}|20[0-2]\d)\b", str(act_data["an_act"]))
                        if an_curat:
                            act_data["an_act"] = an_curat.group(1)
                            
                    if not act_data["mo_an"]:
                        act_data["mo_an"] = an_implicit
                        
                    catalog_acte.append(act_data)
                    
        except Exception as e:
            print(f"   ⚠️ Eroare la parsarea fișierului {nume_xml}: {e}")
            
    print(f"\n📊 Extracție completă! Am strâns {len(catalog_acte)} înregistrări brute.")
    
    if catalog_acte:
        salveaza_csv_in_drive(service, "raw_catalog_acte.csv", fieldnames, catalog_acte)
        print("🚀 Gata! Tabelul master a fost salvat curat în folderul de metadate.")
    else:
        print("⚠️ Nu s-au putut extrage date.")

if __name__ == "__main__":
    parcurge_si_extrage()
