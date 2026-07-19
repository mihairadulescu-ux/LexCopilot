import os
import json
from googleapiclient.errors import HttpError

# Încarcă automat toate folderele din variabila de mediu, curățate de spații
TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")
FOLDER_IDS = [fid.strip() for fid in TARGET_FOLDERS_RAW.split(",") if fid.strip()]

def salveaza_xml_in_drive_dinamic(service, nume_fisier, continut_xml):
    """
    Încearcă să salveze fișierul XML în primul folder disponibil.
    Dacă folderul este plin, trece automat și transparent la următorul ID.
    """
    if not FOLDER_IDS:
        print("🛑 Eroare: Nu s-a găsit niciun ID de folder valid în DRIVE_FOLDER_XML!")
        return False

    for folder_id in FOLDER_IDS:
        try:
            # Structura fișierului pentru Google Drive API
            file_metadata = {
                'name': nume_fisier,
                'parents': [folder_id]
            }
            
            # Media configuration pentru upload text direct
            from googleapiclient.http import MediaIoBaseUpload
            import io
            media = MediaIoBaseUpload(io.BytesIO(continut_xml.encode('utf-8')), mimetype='text/xml')
            
            # Încercăm upload-ul
            file_uploaded = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id',
                supportsAllDrives=True
            ).execute()
            
            # Dacă am ajuns aici, upload-ul a reușit cu succes în acest folder!
            # Putem opri căutarea și returnăm ID-ul fișierului salvat.
            return file_uploaded.get('id')
            
        except HttpError as e:
            # Verificăm dacă eroarea este din cauza stocării sau a limitelor de volum
            eroare_text = str(e).lower()
            if "storage" in eroare_text or "limit" in eroare_text or "quota" in eroare_text or "403" in eroare_text:
                print(f"⚠️ [Folder Plin] ID: {folder_id} a respins fișierul din cauza limitelor Google Drive.")
                print("▶️ Comutare automată și transparentă către următorul folder disponibil din listă...")
                continue  # Sare la următorul ID din buclă (loop)
            else:
                # Dacă e alt tip de eroare gravă (ex: permisiuni), o afișăm dar încercăm să nu oprim procesul
                print(f"❌ Eroare neprevăzută la folderul {folder_id}: {e}")
                continue
                
    print("🛑 EROARE CRITICĂ: Toate folderele din listă sunt pline sau inaccesibile!")
    return False
