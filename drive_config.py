"""
================================================================================
          MODUL CENTRALIZAT DE CONFIGURARE & UTILITARE GOOGLE DRIVE
================================================================================

INSTRUCȚIUNI DE UTILIZARE:
--------------------------
1. Plasare fișier:
   - Salvați acest fișier ca 'drive_config.py' direct în RĂDĂCINA repository-ului 
     (LexCopilot/drive_config.py).

2. Importare în orice script (XML, PDF etc.):
   from drive_config import (
       INDEX_FILE_ID,
       FOLDER_TEMP_INDEXES_ID,
       FOLDERE_XML_IDS,
       FOLDERE_PDF_IDS,
       get_file_params,
       get_list_params,
   )

3. Utilizarea funcțiilor helper pentru operațiuni Google Drive API v3:

   A) Pentru interogări de metadate / verificare fișier (service.files().get):
      meta = service.files().get(**get_file_params(
          fileId=id_fisier, 
          fields="id, name, size"
      )).execute()

   B) Pentru liste / căutări în foldere de Shared Drive (service.files().list):
      rezultat = service.files().list(**get_list_params(
          q="name = 'test.xml' and trashed = false", 
          pageSize=100
      )).execute()

   C) Pentru descărcare de conținut media (service.files().get_media):
      bytes_continut = service.files().get_media(**get_file_params(
          fileId=id_fisier, 
          acknowledgeAbuse=True
      )).execute()

AVANTAJE:
---------
- Elimină automat ghilimelele, spațiile parazite și newlines din variabilele GitHub.
- Injectează automat flag-urile legale obligatorii pentru Shared Drives 
  (supportsAllDrives / includeItemsFromAllDrives) prevenind erorile 404 sau de sintaxă.
================================================================================
"""

import os

# ==============================================================================
# 1. FUNCTOR DE CURĂȚARE ȘI IGIENIZARE A VARIABILELOR DE MEDIU
# ==============================================================================
def curata_var(nume_var, valoare_default=""):
    """
    Curăță strict orice variabilă de mediu de ghilimele (simple/duble),
    spații și caractere de linie nouă (CRLF).
    """
    val = os.getenv(nume_var, "").strip()
    val = val.replace('"', '').replace("'", "").replace("\n", "").replace("\r", "").strip()
    return val if val else valoare_default


# ==============================================================================
# 2. VARIABILE GLOBALE DE MEDIU PENTRU DRIVE (CURĂȚATE PENTRU TOT PROIECTUL)
# ==============================================================================
DEFAULT_TEMP_FOLDER_ID = "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"

# Baze de date & Indecși
INDEX_FILE_ID = curata_var("XML_STORAGE_INDEX")
FOLDER_TEMP_INDEXES_ID = curata_var("TEMPORARY_XML_INDEXES", DEFAULT_TEMP_FOLDER_ID)
FOLDER_METADATA_ID = curata_var("METADATA_FOLDER_ID", DEFAULT_TEMP_FOLDER_ID)

# Liste de Shared Drives XML
FOLDERE_XML_RAW = curata_var("DRIVE_FOLDER_XML")
FOLDERE_XML_IDS = [
    fid.strip()
    for fid in FOLDERE_XML_RAW.split(",")
    if fid.strip()
] or [
    "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m",
    "1G7CkaoivnTR0O8mZceB0143Q6956C1-1",
    "1T2N_v81889Y7tyHUbrTSLR073YC7mGk5",
    "1NWe4JKhhaQ4HxFGs7FfhxnlemE0ZM2E2
    "1JTf2oO_pBBYqWJv-FNoM8xy55uYCB7cX"
]

# Liste de Shared Drives PDF (Pregătite pentru extinderea pe PDF-uri)
FOLDERE_PDF_RAW = curata_var("DRIVE_FOLDER_PDF")
FOLDERE_PDF_IDS = [
    fid.strip()
    for fid in FOLDERE_PDF_RAW.split(",")
    if fid.strip()
]


# ==============================================================================
# 3. HELPER-E OBLIGATORII PENTRU SHARED GOOGLE DRIVES (API v3)
# ==============================================================================
def get_file_params(**extra_params):
    """
    Injectează AUTOMAT parametrii legali obligatorii pentru operarea pe un fișier specific
    în Shared Drives via service.files().get() sau service.files().get_media().
    """
    base_params = {
        "supportsAllDrives": True,
    }
    base_params.update(extra_params)
    return base_params


def get_list_params(**extra_params):
    """
    Injectează AUTOMAT parametrii legali obligatorii pentru căutare / listare de foldere
    în Shared Drives via service.files().list().
    """
    base_params = {
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
    }
    base_params.update(extra_params)
    return base_params
