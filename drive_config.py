import os
import sys

# Standard logare live
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Citim variabila FOLDERE_XML_RAW din mediul GitHub Actions (Single Source of Truth)
FOLDERE_XML_RAW = os.getenv("FOLDERE_XML_RAW", "").strip()

if FOLDERE_XML_RAW:
    # Curățăm ghilimelele, spațiile și caracterele inutile din fiecare ID
    FOLDERE_XML_IDS = [
        fid.strip().strip('"').strip("'") 
        for fid in FOLDERE_XML_RAW.split(",") 
        if fid.strip().strip('"').strip("'")
    ]
else:
    print("⚠️ [AVERTISMENT] Variabila FOLDERE_XML_RAW nu a fost găsită în mediu!", flush=True)
    FOLDERE_XML_IDS = []

if not FOLDERE_XML_IDS:
    print("🛑 [EROARE CRITICĂ] Nu există niciun ID de folder configurat în FOLDERE_XML_RAW!", flush=True)
    sys.exit(1)

print(f"📊 [CONFIG DRIVE] Au fost încărcate dinamic {len(FOLDERE_XML_IDS)} Shared Drive-uri XML.", flush=True)
