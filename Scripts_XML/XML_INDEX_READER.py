import os
import sys
import json
import gzip

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

NOME_INDEX_MASTER = "index_xml.json.gz"

def incarc_index_master_gz(cale_local_sau_stream):
    """Încarcă indexul master din arhivă GZIP direct în memorie."""
    try:
        with gzip.open(cale_local_sau_stream, "rb") as f:
            date = json.loads(f.read().decode('utf-8'))
            print(f"✅ [INDEX READER] Master Index încărcat cu succes ({len(date):,} intrări).", flush=True)
            return date
    except Exception as e:
        print(f"⚠️ [INDEX READER] Nu s-a putut citi indexul comprimat (.gz): {e}", flush=True)
        return {}

def salveaza_index_master_gz(date_index, cale_salvare):
    """Salvează dicționarul global sub formă comprimată .json.gz."""
    try:
        with gzip.open(cale_salvare, "wb") as f:
            f.write(json.dumps(date_index, ensure_ascii=False, indent=2).encode('utf-8'))
        print(f"💾 [INDEX READER] Master Index salvat comprimat la: {cale_salvare}", flush=True)
        return True
    except Exception as e:
        print(f"🛑 [INDEX READER] Eroare la salvarea indexului master: {e}", flush=True)
        return False

def obtine_index_virtual(drive_service):
    """Reconstruiește 'Indexul Virtual' la secundă combinând Master Index cu toți Micro-indecșii."""
    print("\n⚡ [INDEX READER] Construire Index Virtual LIVE...", flush=True)
    fisiere_map = {}
    
    id_index_drive = os.getenv("XML_STORAGE_INDEX")
    id_folder_temp = os.getenv("TEMPORARY_XML_INDEXES")
    
    # A. Încărcare Master Index
    if not id_index_drive:
        print("⚠️ [INDEX READER] CRITIC: Variabila 'XML_STORAGE_INDEX' nu este setată în mediu!", flush=True)
    else:
        try:
            print(f"📥 [INDEX READER] Descărcare Master Index (ID: {id_index_drive})...", flush=True)
            request = drive_service.files().get_media(fileId=id_index_drive)
            with open(NOME_INDEX_MASTER, "wb") as f:
                f.write(request.execute())
                
            master_data = incarc_index_master_gz(NOME_INDEX_MASTER)
            if master_data:
                fisiere_map.update(master_data)
        except Exception as e:
            print(f"⚠️ [INDEX READER] Eroare la Master Index: {e}. Se continuă.", flush=True)

    # B. Încărcare Micro-indecși
    if not id_folder_temp:
        print("⚠️ [INDEX READER] CRITIC: Variabila 'TEMPORARY_XML_INDEXES' nu este setată în mediu!", flush=True)
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
                print("ℹ️ [INDEX READER] Niciun micro-index găsit.", flush=True)
        except Exception as e:
            print(f"⚠️ [INDEX READER] Eroare la căutarea micro-indecșilor: {e}", flush=True)

    return fisiere_map
