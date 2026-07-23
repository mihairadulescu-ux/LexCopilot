import os
import sys
import json
import gzip

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

NOME_INDEX_MASTER = "index_xml.json.gz"


def incarc_index_master_gz(cale_local_sau_stream):
    """
    Încarcă Master Index-ul. 
    Încearcă mai întâi ca arhivă GZIP reală (.gz). 
    Dacă fișierul de pe Drive a fost salvat necomprimat (JSON simplu), face fallback automat.
    """
    # 1. Încercare dezarhivare GZIP
    try:
        if isinstance(cale_local_sau_stream, str):
            with gzip.open(cale_local_sau_stream, "rb") as f:
                date = json.loads(f.read().decode('utf-8'))
        else:
            date_bytes = gzip.decompress(cale_local_sau_stream)
            date = json.loads(date_bytes.decode('utf-8'))
            
        print(f"✅ [INDEX READER] Master Index încărcat cu succes din GZIP ({len(date):,} intrări).", flush=True)
        return date
    except Exception as e_gz:
        # 2. Fallback: încercăm citire ca JSON simplu (dacă fișierul de pe Drive nu era compresat)
        try:
            if isinstance(cale_local_sau_stream, str):
                with open(cale_local_sau_stream, "r", encoding="utf-8") as f:
                    date = json.load(f)
            else:
                date = json.loads(cale_local_sau_stream.decode('utf-8'))
                
            print(f"⚠️ [INDEX READER] Master Index era JSON necomprimat! Încărcat cu succes ({len(date):,} intrări).", flush=True)
            return date
        except Exception as e_json:
            print(f"⚠️ [INDEX READER] Nu s-a putut citi Master Index (GZIP err: {e_gz} | JSON err: {e_json})", flush=True)
            return {}


def salveaza_index_master_gz(date_index, cale_salvare):
    """Salvează dicționarul global sub formă comprimată GZIP reală (.json.gz)."""
    try:
        with gzip.open(cale_salvare, "wb") as f:
            f.write(json.dumps(date_index, ensure_ascii=False, indent=2).encode('utf-8'))
        print(f"💾 [INDEX READER] Master Index salvat comprimat GZIP la: {cale_salvare}", flush=True)
        return True
    except Exception as e:
        print(f"🛑 [INDEX READER] Eroare la salvarea indexului master: {e}", flush=True)
        return False


def adauga_sau_actualizeaza_pointer_fisier(index_data, nume_fisier, an, pagina, drive_id, tip_stocare="individual", arhiva=None, cale_interna=None):
    """Adaugă sau actualizează starea unui fișier în index conform schemei oficiale."""
    index_data[nume_fisier] = {
        "an": int(an),
        "pagina": int(pagina),
        "tip_stocare": tip_stocare,
        "arhiva": arhiva,
        "cale_interna": cale_interna,
        "drive_id": drive_id
    }


def obtine_index_virtual(drive_service):
    """
    Reconstruiește 'Indexul Virtual' combinând Master Index de pe Drive 
    cu toți Micro-indecșii neconsolidați din folderul temporary.
    """
    print("\n⚡ [INDEX READER] Construire Index Virtual LIVE...", flush=True)
    fisiere_map = {}
    
    id_index_drive = os.getenv("XML_STORAGE_INDEX")
    id_folder_temp = os.getenv("TEMPORARY_XML_INDEXES")
    
    # A. Încărcare Master Index
    if not id_index_drive:
        print("⚠️ [INDEX READER] Variabila 'XML_STORAGE_INDEX' nu este setată în mediu!", flush=True)
    else:
        try:
            print(f"📥 [INDEX READER] Descărcare Master Index (ID: {id_index_drive})...", flush=True)
            request = drive_service.files().get_media(fileId=id_index_drive)
            continut_bytes = request.execute()
            
            master_data = incarc_index_master_gz(continut_bytes)
            if master_data:
                fisiere_map.update(master_data)
        except Exception as e:
            print(f"⚠️ [INDEX READER] Eroare la preluarea Master Index de pe Drive: {e}", flush=True)

    # B. Încărcare Micro-indecși
    if not id_folder_temp:
        print("⚠️ [INDEX READER] Variabila 'TEMPORARY_XML_INDEXES' nu este setată în mediu!", flush=True)
    else:
        print("🔍 [INDEX READER] Se caută micro-indecșii neconsolidați...", flush=True)
        try:
            rezultat_micro = drive_service.files().list(
                q=f"'{id_folder_temp}' in parents and trashed=false and name contains 'temp_index_'",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="files(id, name)"
            ).execute()
            
            micro_files = rezultat_micro.get('files', [])
            if micro_files:
                print(f"🧩 [INDEX READER] Găsiți {len(micro_files)} micro-indecși. Integrare în memorie...", flush=True)
                for mf in micro_files:
                    try:
                        req_micro = drive_service.files().get_media(fileId=mf['id'])
                        continut_micro = req_micro.execute()
                        date_micro = json.loads(continut_micro.decode('utf-8'))
                        
                        updates = date_micro.get("flag_updates", {})
                        fisiere_map.update(updates)
                    except Exception as e_micro:
                        print(f"⚠️ [INDEX READER] Eroare citire micro-index {mf['name']}: {e_micro}", flush=True)
            else:
                print("ℹ️ [INDEX READER] Niciun micro-index neconsolidat găsit.", flush=True)
        except Exception as e:
            print(f"⚠️ [INDEX READER] Eroare la căutarea micro-indecșilor: {e}", flush=True)

    print(f"✅ [INDEX READER] Index Virtual gata! Total fișiere cunoscute: {len(fisiere_map):,}\n", flush=True)
    return fisiere_map
