import os
import sys
import csv
import json
import re
import io
import time
from datetime import datetime, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# Importăm cititorul de index virtual actualizat la secundă
from XML_INDEX_READER import obtine_index_virtual

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

# Folderul de destinație pentru fișierele CSV finale de metadate
FOLDER_METADATE_ID = os.getenv("METADATA_FOLDER_ID", "").strip()

# Folderul pentru micro-indecșii temporari de sincronizare real-time
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES", "").replace('"', '').replace("'", "").strip() or "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"

if not FOLDER_METADATE_ID:
    FOLDERE_XML_RAW = os.getenv("DRIVE_FOLDER_XML", "").replace('"', '').replace("'", "").replace("\n", "").replace("\r", "")
    FOLDERE_XML_IDS = [fid.strip() for fid in FOLDERE_XML_RAW.split(",") if fid.strip()]
    FOLDER_METADATE_ID = FOLDERE_XML_IDS[0] if FOLDERE_XML_IDS else None


def get_drive_service():
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


def salveaza_micro_index_temporar(service, flag_updates):
    """
    Creează un fișier temporar de mutații pe Drive (în TEMPORARY_XML_INDEXES) 
    pentru a anunța toate celelalte scripturi că aceste fișiere au Tags_extracted = True.
    """
    if not flag_updates:
        return

    timestamp = int(time.time())
    nume_temp = f"temp_index_dictionaries_{timestamp}.json"
    
    structura_log = {
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "download_XML_dictionaries.py",
        "flag_updates": flag_updates
    }

    # Salvare locală temporară
    with open(nume_temp, "w", encoding="utf-8") as f:
        json.dump(structura_log, f, ensure_ascii=False, indent=2)

    # Încărcare pe Drive în folderul temporar
    try:
        media = MediaFileUpload(nume_temp, mimetype='application/json')
        file_metadata = {
            'name': nume_temp,
            'parents': [FOLDER_TEMP_INDEXES_ID]
        }
        res = service.files().create(
            body=file_metadata, 
            media_body=media, 
            supportsAllDrives=True, 
            fields='id'
        ).execute()
        
        print(f"{VERDE}⚡ [Micro-Index Publicat] Înregistrat flag-ul 'Tags_extracted: True' pentru {len(flag_updates)} fișiere (ID Temp: {res.get('id')}){RESET}", flush=True)
    except Exception as e:
        print(f"{ROSU}⚠️ Nu s-a putut publica micro-indexul temporar pe Drive: {e}{RESET}", flush=True)
    finally:
        if os.path.exists(nume_temp):
            os.remove(nume_temp)


def incarca_pe_drive(service, cale_fisier_local, folder_id):
    if not folder_id:
        print(f"⚠️ Nu s-a specificat ID-ul folderului de destinație pe Drive pentru {cale_fisier_local}.", flush=True)
        return

    nume_fisier = os.path.basename(cale_fisier_local)
    media = MediaFileUpload(cale_fisier_local, mimetype='text/csv', resumable=True)

    try:
        query = f"'{folder_id}' in parents and name = '{nume_fisier}' and trashed = false"
        res = service.files().list(q=query, spaces='drive', fields='files(id)', supportsAllDrives=True).execute()
        files = res.get('files', [])

        if files:
            file_id = files[0]['id']
            service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            print(f"{VERDE}✅ Sincronizat pe Drive (Update) în Metadate: {nume_fisier} (ID: {file_id}){RESET}", flush=True)
            return

        file_metadata = {'name': nume_fisier, 'parents': [folder_id]}
        f_nou = service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True, fields='id').execute()
        print(f"{VERDE}🎉 Încarcat pe Drive (Nou) în Metadate: {nume_fisier} (ID: {f_nou.get('id')}){RESET}", flush=True)

    except Exception as e:
        print(f"{ROSU}❌ Eroare încărcare Drive {nume_fisier}:{RESET} {e}", flush=True)


def extrage_taguri_din_matrice(service, ani_procesare):
    # 🚀 Obținem indexul virtual ultra-actualizat
    index_v = obtine_index_virtual(service)
    fisiere_map = index_v.get("fisiere", {})

    emitenti_gasiti = set()
    tipuri_acte_gasite = set()

    regex_emitent = re.compile(r"<[^>]*?Emitent[^>]*?>(.*?)</[^>]*?Emitent>", re.DOTALL | re.IGNORECASE)
    regex_tip_act = re.compile(r"<[^>]*?TipAct[^>]*?>(.*?)</[^>]*?TipAct>", re.DOTALL | re.IGNORECASE)

    # Filtrăm doar fișierele din anii ceruți care NU au fost procesate deja (Tags_extracted == False)
    fisiere_tinta = [
        (nume, info) for nume, info in fisiere_map.items() 
        if info.get('an') in ani_procesare and not info.get('Tags_extracted', False)
    ]

    string_ani = "_".join([str(a) for a in ani_procesare])
    print(f"\n{GALBEN}⚡ [Dictionare] Scanare pe indexul virtual pentru anii {string_ani} ({len(fisiere_tinta)} fișiere neprocesate selectate)...{RESET}", flush=True)

    contor_total_procesat = 0
    flag_updates = {}

    for nume_fisier, info in fisiere_tinta:
        file_id = info.get('id')
        if not file_id:
            continue

        try:
            cerere = service.files().get_media(fileId=file_id, supportsAllDrives=True)
            fh = io.BytesIO()
            descarcare = MediaIoBaseDownload(fh, cerere)
            gata = False
            while not gata:
                _, gata = descarcare.next_chunk()
            
            xml_text = fh.getvalue().decode("utf-8", errors="ignore")
            
            for em in regex_emitent.findall(xml_text):
                val = em.strip()
                if val: 
                    emitenti_gasiti.add(val)
                
            for ta in regex_tip_act.findall(xml_text):
                val = ta.strip()
                if val: 
                    tipuri_acte_gasite.add(val)

            # Marcăm fișierul ca procesat pentru starea de mutație
            flag_updates[nume_fisier] = {"Tags_extracted": True}
            contor_total_procesat += 1

            if contor_total_procesat % 500 == 0:
                print(f"   📊 [Progres] Procesate: {contor_total_procesat}/{len(fisiere_tinta)} fișiere", flush=True)

        except Exception:
            continue

    print(f"\n✅ [Procesare Finalizată] Total fișiere scanate: {contor_total_procesat}", flush=True)

    # 💾 Salvăm mutațiile în folderul temporar de pe Drive
    salveaza_micro_index_temporar(service, flag_updates)

    cale_emitenti = f"lista_emitenti_{string_ani}.csv"
    cale_acte = f"lista_tip_acte_{string_ani}.csv"
    
    with open(cale_emitenti, mode='w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['Emitent'])
        for e in sorted(list(emitenti_gasiti)):
            writer.writerow([e])
            
    with open(cale_acte, mode='w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['Tip_Act'])
        for t in sorted(list(tipuri_acte_gasite)):
            writer.writerow([t])
            
    print(f"{VERDE}✅ [Salvat Local] '{cale_emitenti}' și '{cale_acte}'. Se încarcă în folderul Metadate...{RESET}", flush=True)

    incarca_pe_drive(service, cale_emitenti, FOLDER_METADATE_ID)
    incarca_pe_drive(service, cale_acte, FOLDER_METADATE_ID)


if __name__ == "__main__":
    argumente_numerice = []
    for arg in sys.argv[1:]:
        piese = arg.split()
        for piesa in piese:
            if piesa.isdigit():
                argumente_numerice.append(int(piesa))

    if len(argumente_numerice) == 1:
        ani_finali = [argumente_numerice[0]]
    elif len(argumente_numerice) >= 2:
        ani_finali = list(range(argumente_numerice[0], argumente_numerice[1] + 1))
    else:
        print(f"{ROSU}🛑 Eroare: Lipsesc anii ca parametru!{RESET}")
        sys.exit(1)
        
    drive_service = get_drive_service()
    extrage_taguri_din_matrice(drive_service, ani_finali)
