import os
import json
import io
import re
from googleapiclient.http import MediaIoBaseDownload

CALE_INDEX_LOCAL = "index_xml.json"

def incarca_sau_sincronizeaza_index(service, id_folder_master):
    """
    1. Trage index_xml.json din Google Drive.
    2. Caută prin Drive dacă există fișiere noi apărute DUPĂ 'last_updated' din index.
    3. Returnează lista completă și actualizată de fișiere în memorie.
    """
    # 1. Descărcăm indexul din Drive
    print("📥 Preluare 'index_xml.json' din Google Drive...")
    query = f"'{id_folder_master}' in parents and name = '{CALE_INDEX_LOCAL}' and trashed = false"
    data_index = {"last_updated": None, "fisiere": []}
    
    try:
        rezultat = service.files().list(q=query, fields="files(id)").execute()
        fisiere = rezultat.get('files', [])
        if fisiere:
            cerere = service.files().get_media(fileId=fisiere[0]['id'])
            fh = io.FileIO(CALE_INDEX_LOCAL, 'wb')
            downloader = MediaIoBaseDownload(fh, cerere)
            gata = False
            while not gata:
                _, gata = downloader.next_chunk()
            
            with open(CALE_INDEX_LOCAL, 'r', encoding='utf-8') as f:
                data_index = json.load(f)
            print(f"✅ Index încărcat în memorie ({len(data_index.get('fisiere', []))} fișiere, timestamp: {data_index.get('last_updated')}).")
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca indexul din Drive: {e}")

    last_updated = data_index.get("last_updated")
    fisiere_map = {f['id']: f for f in data_index.get("fisiere", [])}

    # 2. Căutare delta ultra-rapidă pentru noutăți apărute între timp
    if last_updated:
        folder_ids_raw = os.getenv("DRIVE_FOLDER_XML", id_folder_master)
        folder_ids = [fid.strip() for fid in folder_ids_raw.replace('"', '').replace("'", "").split(",") if fid.strip()]
        
        noutati_numar = 0
        for f_id in folder_ids:
            query_delta = f"'{f_id}' in parents and name contains 'brut_legislatie_' and modifiedTime > '{last_updated}' and trashed = false"
            try:
                page_token = None
                while True:
                    resp = service.files().list(
                        q=query_delta, spaces='drive', fields='nextPageToken, files(id, name, description)', pageSize=1000, pageToken=page_token
                    ).execute()
                    
                    for item in resp.get('files', []):
                        if item['id'] not in fisiere_map:
                            desc = item.get('description', '')
                            fisiere_map[item['id']] = {
                                'id': item['id'],
                                'name': item['name'],
                                'processed': (desc == 'processed=true' or 'processed=true' in desc),
                                'folder_id': f_id
                            }
                            noutati_numar += 1
                    page_token = resp.get('nextPageToken')
                    if not page_token: break
            except Exception: pass
            
        if noutati_numar > 0:
            print(f"⚡ [Noutăți Detectate] Am găsit {noutati_numar} fișiere adăugate după generarea indexului.")

    return list(fisiere_map.values())

def filtreaza_fisiere_an(fisiere_lista, an_tinta, doar_neprocesate=False):
    """
    Filtrează lista de fișiere din memorie pentru un an specific.
    Poate returna doar fișierele neprocesate (processed == False).
    """
    rezultat = []
    pattern = re.compile(rf"^brut_legislatie_{an_tinta}_pag\d+\.xml$")
    
    for f in fisiere_lista:
        if pattern.match(f.get('name', '')):
            if doar_neprocesate and f.get('processed', False):
                continue
            rezultat.append(f)
            
    return rezultat
