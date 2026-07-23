import os
import sys

# Standard logare live instantanee
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Citim variabila oficială din mediu: DRIVE_FOLDER_XML
DRIVE_FOLDER_XML_RAW = os.getenv("DRIVE_FOLDER_XML", "").strip()

if DRIVE_FOLDER_XML_RAW:
    # Curățăm ghilimelele, spațiile și caracterele inutile din fiecare ID
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

print(f"📊 [CONFIG DRIVE] Au fost încărcate dinamic {len(FOLDERE_XML_IDS)} Shared Drive-uri XML.", flush=True)

# -------------------------------------------------------------------
# FOLDER TEMPORAR PENTRU MICRO-INDECSi (Necesar de download_XML.py)
# -------------------------------------------------------------------
# Dacă ai o variantă dedicată FOLDER_TEMP_INDEXES_ID în mediu o luăm de acolo,
# altfel folosim automat primul Shared Drive din listă.
FOLDER_TEMP_INDEXES_ID = os.getenv("FOLDER_TEMP_INDEXES_ID", FOLDERE_XML_IDS[0] if FOLDERE_XML_IDS else "")
