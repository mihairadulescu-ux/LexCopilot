import os
import sys
import json
import gzip
from drive_config import FOLDERE_XML_IDS

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

NOME_INDEX_MASTER = "index_xml.json.gz"

def incarc_index_master_gz(cale_local_sau_stream):
    """
    Încarcă indexul master din arhivă GZIP direct în memorie.
    """
    try:
        with gzip.open(cale_local_sau_stream, "rb") as f:
            date = json.loads(f.read().decode('utf-8'))
            print(f"✅ [INDEX READER] Master Index încărcat cu succes ({len(date)} intrări).", flush=True)
            return date
    except Exception as e:
        print(f"⚠️ [INDEX READER] Nu s-a putut citi indexul comprimat (.gz): {e}", flush=True)
        return {}

def salveaza_index_master_gz(date_index, cale_salvare):
    """
    Salvează dicționarul global sub formă comprimată .json.gz.
    """
    try:
        with gzip.open(cale_salvare, "wb") as f:
            f.write(json.dumps(date_index, ensure_ascii=False, indent=2).encode('utf-8'))
        print(f"💾 [INDEX READER] Master Index salvat comprimat la: {cale_salvare}", flush=True)
        return True
    except Exception as e:
        print(f"🛑 [INDEX READER] Eroare la salvarea indexului master: {e}", flush=True)
        return False

def adauga_sau_actualizeaza_pointer_fisier(index_data, nume_fisier, an, pagina, drive_id, tip_stocare="archive", nume_arhiva=None):
    """
    Adaugă sau actualizează starea unui fișier în index (pointer hibrid: individual vs archive).
    """
    index_data[nume_fisier] = {
        "an": int(an),
        "pagina": int(pagina),
        "tip_stocare": tip_stocare,  # "individual" sau "archive"
        "arhiva": nume_arhiva if tip_stocare == "archive" else None,
        "cale_interna": nume_fisier if tip_stocare == "archive" else None,
        "drive_id": drive_id
    }

if __name__ == "__main__":
    print(f"📊 [INDEX READER] Configurat pentru cele {len(FOLDERE_XML_IDS)} Shared Drive-uri dinamice.", flush=True)
