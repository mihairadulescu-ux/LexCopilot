import os
import sys
import json
import io
import re
from pathlib import Path
from googleapiclient.http import MediaIoBaseDownload

# ==============================================================================
# CONFIGURARE CĂI DE IMPORT (PENTRU RULARE DIN GITHUB ACTIONS SAU LOCAL)
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

# Importăm configurația centralizată și parametrii securizați pentru Shared Drive
from drive_config import (
    FOLDERE_XML_IDS,
    get_file_params,
    get_list_params,
)

CALE_INDEX_LOCAL = "index_xml.json"


def incarca_sau_sincronizeaza_index(service, id_folder_master):
    """
    1. Trage index_xml.json din Google Drive (Shared Drive compatible).
    2. Caută prin Drive dacă există fișiere noi apărute DUPĂ 'last_updated' din index.
    3. Returnează lista completă și actualizată de fișiere în memorie.
    """
    # 1. Descărcăm indexul din Drive
    print("📥 Preluare 'index_xml.json' din Google Drive...", flush=True)
    query = f"'{id_folder_master}' in parents and name = '{CALE_INDEX_LOCAL}' and trashed = false"
    data_index = {"last_updated": None, "fisiere": []}

    try:
        # Căutare fișier pe Shared Drive
        rezultat = service.files().list(
            **get_list_params(q=query, fields="files(id)")
        ).execute()
        
        fisiere = rezultat.get('files', [])
        if fisiere:
            file_id = fisiere[0]['id']
            
            # Descărcare conținut media
            cerere = service.files().get_media(
                **get_file_params(fileId=file_id, acknowledgeAbuse=True)
            )
            fh = io.FileIO(CALE_INDEX_LOCAL, 'wb')
            downloader = MediaIoBaseDownload(fh, cerere)
            gata = False
            while not gata:
                _, gata = downloader.next_chunk()

            with open(CALE_INDEX_LOCAL, 'r', encoding='utf-8') as f:
                data_index = json.load(f)
            print(f"✅ Index încărcat în memorie ({len(data_index.get('fisiere', []))} fișiere, timestamp: {data_index.get('last_updated')}).", flush=True)

    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca indexul din Drive: {e}", flush=True)

    last_updated = data_index.get("last_updated")
    fisiere_map = {f['id']: f for f in data_index.get("fisiere", [])}

    # 2. Căutare delta ultra-rapidă pentru noutăți apărute între timp
    if last_updated:
        # Folosim lista curățată din drive_config sau fallback pe folderul specificat
        folder_ids = FOLDERE_XML_IDS if FOLDERE_XML_IDS else [id_folder_master]

        noutati_numar = 0
        for f_id in folder_ids:
            query_delta = f"'{f_id}' in parents and name contains 'brut_legislatie_' and modifiedTime > '{last_updated}' and trashed = false"
            try:
                page_token = None
                while True:
                    resp = service.files().list(
                        **get_list_params(
                            q=query_delta,
                            spaces='drive',
                            fields='nextPageToken, files(id, name, description)',
                            pageSize=1000,
                            pageToken=page_token
                        )
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
                    if not page_token:
                        break
            except Exception as e:
                print(f"⚠️ Eroare verificare delta pe folderul {f_id[:8]}: {e}", flush=True)

        if noutati_numar > 0:
            print(f"⚡ [Noutăți Detectate] Am găsit {noutati_numar} fișiere adăugate după generarea indexului.", flush=True)

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
