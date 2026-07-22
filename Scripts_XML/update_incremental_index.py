# Scripts_XML/update_incremental_index.py
import sys
from pathlib import Path

DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent
sys.path.insert(0, str(RADACINA_PROIECT))

from googleapiclient.discovery import build
import XML_INDEX_READER
import build_index

def main():
    print("⚡ Rulare rapidă Incremental Index (Delta + Micro-Indexes)...", flush=True)
    service = build_index.get_drive_service()
    
    # Incarca indexul virtual actualizat (Master + Temp-uri + Delta)
    index_v = XML_INDEX_READER.obtine_index_virtual(service)
    
    # Salveaza Master Index-ul actualizat direct pe Drive (fara re-scanare fizica)
    build_index.salveaza_master_index_xml(
        service, 
        index_v, 
        mesaj="Master Index XML Actualizat Incremental"
    )
    print("✅ Index Incremental salvat în câteva secunde!", flush=True)

if __name__ == "__main__":
    main()
