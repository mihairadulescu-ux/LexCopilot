import os
import sys
import time
import json
import csv
import io
import re
from pathlib import Path
from bs4 import BeautifulSoup

# ==============================================================================
# CONFIGURARE CĂI DE IMPORT
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from drive_config import (
    FOLDER_TEMP_INDEXES_ID,
    get_file_params,
    get_list_params,
)

import XML_INDEX_READER

# Folderul de destinație specificat pentru salvarea metadatelor
METADATA_FOLDER_ID = "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"

NUME_CSV_EMITENTI = "emitenți_brut.csv"
NUME_CSV_TIPURI_ACTE = "tipuri_acte_brut.csv"
INTERVAL_SALVARE = 10000  # Salvare la fiecare 10.000 de fișiere prelucrate


# ==============================================================================
# AUTENTIFICARE GOOGLE DRIVE API
# ==============================================================================
def get_drive_service():
    """Autentificare în Google Drive API."""
    creds_json = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GDRIVE_SERVICE_ACCOUNT_KEY")
        or os.getenv("SERVICE_ACCOUNT_JSON")
    )

    if creds_json:
        try:
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare la citirea secretului JSON: {e}", flush=True)
            sys.exit(1)

    cale_local = RADACINA_PROIECT / "service_account.json"
    if cale_local.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(cale_local), scopes=["https://www.googleapis.com/auth/drive"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            print(f"❌ Eroare la citirea fișierului local service_account.json: {e}", flush=True)

    print("❌ Nu s-a găsit secretul GOOGLE_SERVICE_ACCOUNT_JSON!", flush=True)
    sys.exit(1)


# ==============================================================================
# DESCĂRCARE ȘI INCARCARE CSV EXISTENT DIN DRIVE
# ==============================================================================
def descarca_sau_creeaza_set_csv(service, nume_fisier):
    """Citește CSV-ul existent din Drive pentru a menține unicitatea și frecvența acumulată."""
    set_valori = {}
    query = f"'{METADATA_FOLDER_ID}' in parents and name = '{nume_fisier}' and trashed = false"
    
    try:
        res = service.files().list(**get_list_params(q=query, fields="files(id)")).execute()
        files = res.get("files", [])
        
        if files:
            file_id = files[0]["id"]
            content = service.files().get_media(**get_file_params(fileId=file_id)).execute()
            reader = csv.reader(io.StringIO(content.decode("utf-8")))
            
            # Omitem antetul
            header = next(reader, None)
            for row in reader:
                if row and len(row) >= 2:
                    valoare, aparitii = row[0].strip(), int(row[1])
                    if valoare:
                        set_valori[valoare] = aparitii
            print(f"📥 Încărcat CSV existent '{nume_fisier}': {len(set_valori):,} intrări anterioare.", flush=True)
    except Exception as e:
        print(f"⚠️ Nu s-a putut descărca {nume_fisier} ({e}). Se va începe un fișier nou.", flush=True)
        
    return set_valori


def salveaza_csv_pe_drive(service, set_valori, nume_fisier, antet_coloana):
    """Actualizează fișierul CSV pe Drive în METADATA_FOLDER_ID cu datele consolidate la zi."""
    cale_temp = Path(nume_fisier)
    try:
        # Sortăm după frecvență descrescătoare
        intrarile_sortate = sorted(set_valori.items(), key=lambda x: x[1], reverse=True)

        with open(cale_temp, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([antet_coloana, "Aparitii"])
            for val, count in intrarile_sortate:
                writer.writerow([val, count])

        media = MediaFileUpload(str(cale_temp), mimetype="text/csv")
        query = f"'{METADATA_FOLDER_ID}' in parents and name = '{nume_fisier}' and trashed = false"
        res = service.files().list(**get_list_params(q=query, fields="files(id)")).execute()
        files = res.get("files", [])

        if files:
            file_id = files[0]["id"]
            params = get_file_params(fileId=file_id)
            params["media_body"] = media
            service.files().update(**params).execute()
        else:
            file_metadata = {"name": nume_fisier, "parents": [METADATA_FOLDER_ID]}
            params = get_file_params()
            params["body"] = file_metadata
            params["media_body"] = media
            service.files().create(**params).execute()

        print(f"💾 [FLUSH CSV] Actualizat pe Drive: {nume_fisier} ({len(set_valori):,} intrări unice)", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()
    except Exception as e:
        print(f"❌ Eroare la salvarea CSV-ului {nume_fisier}: {e}", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()


def salveaza_micro_index(service, flag_updates):
    """Persistă starea de procesare a fișierelor prin micro-indecși."""
    if not flag_updates:
        return
    timestamp = int(time.time() * 1000)
    nume_temp = f"temp_index_tags_{timestamp}.json"
    data = {"flag_updates": flag_updates}

    cale_temp = Path(nume_temp)
    try:
        with open(cale_temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        media = MediaFileUpload(str(cale_temp), mimetype="application/json")
        file_metadata = {"name": nume_temp, "parents": [FOLDER_TEMP_INDEXES_ID]}

        params = get_file_params()
        params["body"] = file_metadata
        params["media_body"] = media

        service.files().create(**params).execute()
        print(f"🧩 Micro-index salvat în Drive: {nume_temp} ({len(flag_updates)} fișiere marcate)", flush=True)

        if cale_temp.exists():
            cale_temp.unlink()
    except Exception as e:
        print(f"⚠️ Eroare la salvarea micro-index-ului: {e}", flush=True)
        if cale_temp.exists():
            cale_temp.unlink()


# ==============================================================================
# PARSARE CONȚINUT XML BRUT
# ==============================================================================
def extrage_metadate_din_xml(continut_xml):
    """Extrage lista de Emitenți și Tipuri de Acte din fișierul XML brut Just.ro."""
    emitenți_gasiti = []
    tipuri_acte_gasite = []

    try:
        soup = BeautifulSoup(continut_xml, "xml")
        
        # Căutare tag-uri Emitent
        for tag_emitent in soup.find_all(["Emitent", "emitent", "EMITENT"]):
            text_emitent = tag_emitent.get_text().strip()
            if text_emitent and len(text_emitent) > 1:
                emitenți_gasiti.append(text_emitent)

        # Căutare tag-uri TipAct
        for tag_tip in soup.find_all(["TipAct", "tipAct", "TIPACT", "Tip_Act"]):
            text_tip = tag_tip.get_text().strip()
            if text_tip and len(text_tip) > 1:
                tipuri_acte_gasite.append(text_tip)

    except Exception:
        pass

    return emitenți_gasiti, tipuri_acte_gasite


# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def main():
    print("============================================================", flush=True)
    print("🚀 PORNIRE EXTRAGERE TAG-URI (EMITENȚI ȘI TIPURI ACTE)", flush=True)
    print("============================================================", flush=True)

    service = get_drive_service()

    # 1. Citim fișierele CSV existente din Drive
    map_emitenti = descarca_sau_creeaza_set_csv(service, NUME_CSV_EMITENTI)
    map_tipuri_acte = descarca_sau_creeaza_set_csv(service, NUME_CSV_TIPURI_ACTE)

    # 2. Obținem fișierele neprocesate prin XML_INDEX_READER
    fisiere_tinta = XML_INDEX_READER.obtine_fisiere_neprocesate(service, nume_flag="Tags_extracted")

    if not fisiere_tinta:
        print("✨ Toate fișierele brute au deja tag-urile extrase! Nimic de procesat.", flush=True)
        return

    print(f"📊 Fișiere brute neprocesate identificate: {len(fisiere_tinta):,}", flush=True)

    micro_updates = {}
    fisiere_procesate_sesiune = 0
    fisiere_de_la_ultimul_flush = 0
    timp_start = time.time()

    # 3. Procesare în loturi
    for idx, item in enumerate(fisiere_tinta, start=1):
        nume_fisier = item["nume"]
        file_id = item["id"]

        try:
            # Descărcare conținut XML în memorie
            continut_bytes = (
                service.files()
                .get_media(**get_file_params(fileId=file_id, acknowledgeAbuse=True))
                .execute()
            )
            continut_xml = continut_bytes.decode("utf-8", errors="ignore")

            # Extragere entități
            emitenți, tipuri = extrage_metadate_din_xml(continut_xml)

            for em in emitenți:
                map_emitenti[em] = map_emitenti.get(em, 0) + 1

            for tp in tipuri:
                map_tipuri_acte[tp] = map_tipuri_acte.get(tp, 0) + 1

            # Marcăm fișierul ca având tag-urile extrase
            micro_updates[nume_fisier] = {"Tags_extracted": True}
            fisiere_procesate_sesiune += 1
            fisiere_de_la_ultimul_flush += 1

            # Afișare progres intermediar din 1.000 în 1.000
            if idx % 1000 == 0:
                durata = round(time.time() - timp_start, 1)
                ritm = round(idx / (durata if durata > 0 else 1), 1)
                print(
                    f"⚡ [Progres Processing] {idx:,}/{len(fisiere_tinta):,} fișiere | Ritm: {ritm} f/sec | "
                    f"Emitenți unici: {len(map_emitenti):,} | Tipuri acte unice: {len(map_tipuri_acte):,}",
                    flush=True,
                )

            # SALVARE PERIODICĂ DIN 10.000 ÎN 10.000 DE FIȘIERE
            if fisiere_de_la_ultimul_flush >= INTERVAL_SALVARE or idx == len(fisiere_tinta):
                print(f"\n🔄 [MILESTONE {idx:,}] Se execută salvarea incrementală pe Drive...", flush=True)
                
                # Persistare micro-indecși
                salveaza_micro_index(service, micro_updates)
                micro_updates = {}

                # Salvare/Update CSV-uri
                salveaza_csv_pe_drive(service, map_emitenti, NUME_CSV_EMITENTI, "Emitent_Brut")
                salveaza_csv_pe_drive(service, map_tipuri_acte, NUME_CSV_TIPURI_ACTE, "TipAct_Brut")

                fisiere_de_la_ultimul_flush = 0
                print(f"✅ Milestone {idx:,} salvat cu succes pe Drive!\n", flush=True)

        except Exception as e:
            print(f"⚠️ Eroare la procesarea fișierului {nume_fisier}: {e}", flush=True)

    # Save final de siguranță (dacă au rămas resturi)
    if micro_updates:
        salveaza_micro_index(service, micro_updates)
        salveaza_csv_pe_drive(service, map_emitenti, NUME_CSV_EMITENTI, "Emitent_Brut")
        salveaza_csv_pe_drive(service, map_tipuri_acte, NUME_CSV_TIPURI_ACTE, "TipAct_Brut")

    durata_totala = round(time.time() - timp_start, 1)
    print("\n============================================================", flush=True)
    print(f"🎉 EXTRAGERE FINALIZATĂ în {durata_totala}s!")
    print(f"📊 Fișiere procesate în această sesiune: {fisiere_procesate_sesiune:,}")
    print(f"📊 Total Emitenți unici colectați: {len(map_emitenti):,}")
    print(f"📊 Total Tipuri de Acte unice colectate: {len(map_tipuri_acte):,}")
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
