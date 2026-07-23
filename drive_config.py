import os
import sys

# Logare live instantanee (fără buffering)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# 1. SINGURA SURSĂ DE ADEVĂR: DRIVE_FOLDER_XML
DRIVE_FOLDER_XML_RAW = os.getenv("DRIVE_FOLDER_XML", "").strip()

if DRIVE_FOLDER_XML_RAW:
    FOLDERE_XML_IDS = [
        fid.strip().strip('"').strip("'") 
        for fid in DRIVE_FOLDER_XML_RAW.split(",") 
        if fid.strip().strip('"').strip("'")
    ]
else:
    print("⚠️ [AVERTISMENT] Variabila DRIVE_FOLDER_XML nu a fost găsită în mediu!", flush=True)
    FOLDERE_XML_IDS = []

if not FOLDERE_XML_IDS:
    print("🛑 [EROARE CRITICĂ] Nu există niciun ID configurat în DRIVE_FOLDER_XML!", flush=True)
    sys.exit(1)

print(f"📊 [CONFIG DRIVE] Au fost încărcate dinamic {len(FOLDERE_XML_IDS)} Shared Drive-uri din DRIVE_FOLDER_XML.", flush=True)

# 2. Folder temporar pentru micro-indecși
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES") or FOLDERE_XML_IDS[0]

# 3. Funcții ajutătoare pentru parametrii de stocare / listare cereate de download_XML.py
def get_file_params(nume_fisier):
    is_archive = nume_fisier.endswith(".tar.gz") if isinstance(nume_fisier, str) else False
    return {
        "drive_id": FOLDERE_XML_IDS[0],
        "tip_stocare": "archive" if is_archive else "individual",
        "arhiva": nume_fisier if is_archive else None
    }

# Alias cerut de download_XML.py
def get_list_params():
    return {
        "drive_ids": FOLDERE_XML_IDS,
        "primary_drive_id": FOLDERE_XML_IDS[0],
        "temp_indexes_id": FOLDER_TEMP_INDEXES_ID
    }
