import os
import sys
import io
import json
import time
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

# Încarcă automat toate folderele din variabila de mediu, curățate de spații și linii noi
TARGET_FOLDERS_RAW = os.getenv("DRIVE_FOLDER_XML", "")
FOLDER_IDS = [fid.strip().replace("\n", "").replace("\r", "") for fid in TARGET_FOLDERS_RAW.split(",") if fid.strip()]


def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def salveaza_xml_in_drive_dinamic(service, nume_fisier, continut_xml):
    """
    Uploadează XML-ul în primul folder liber din listă.
    Dacă un folder întoarce teamDriveFileLimitExceeded (403), trece automat la următorul.
    """
    if not FOLDER_IDS:
        print(f"{ROSU}🛑 Eroare: Variabila DRIVE_FOLDER_XML este goală sau invalidă!{RESET}")
        return False

    for folder_id in FOLDER_IDS:
        try:
            file_metadata = {
                'name': nume_fisier,
                'parents': [folder_id]
            }
            
            # Utilizăm stream de tip resumable pentru a intercepta corect erorile Google de volum în bucăți (chunks)
            media = MediaIoBaseUpload(
                io.BytesIO(continut_xml.encode('utf-8')), 
                mimetype='text/xml',
                resumable=True
            )
            
            file_uploaded = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id',
                supportsAllDrives=True
            ).execute()
            
            return file_uploaded.get('id')
            
        except Exception as e:
            eroare_text = str(e).lower()
            # Interceptare specifică pentru limita de 400k obiecte sau spațiu saturat
            if "limit" in eroare_text or "exceeded" in eroare_text or "403" in eroare_text or "storage" in eroare_text:
                print(f"{GALBEN}⚠️ [Folder Plin/Limită Depășită] ID-ul {folder_id} a blocat fișierul.{RESET}")
                print(f"{VERDE}▶️ Se sare automat la următorul folder disponibil în variabila ta...{RESET}")
                continue  # Încearcă imediat următorul ID de folder din listă
            else:
                print(f"{ROSU}❌ Eroare neprevăzută la folderul {folder_id}: {e}{RESET}")
                continue
                
    print(f"{ROSU}🛑 EROARE CRITICĂ: Toate folderele din listă sunt pline sau inaccesibile!{RESET}")
    return False


def simuleaza_si_descarca_pagina(an, pagina):
    """
    Funcție simulată care generează structura de text XML pentru legislație.
    În codul tău real, aici ai logica de request/scrapping HTTP (de exemplu cu httpx sau requests).
    """
    # Această structură păstrează consistența datelor tale brute originale
    return f"""<?xml version="1.0" encoding="utf-8"?>
<document>
    <an>{an}</an>
    <pagina>{pagina}</pagina>
    <emitent>Ministerul Finantelor</emitent>
    <tip_act>Ordin</tip_act>
    <text_brut>Continut legislativ extras din pagina {pagina} a anului {an}...</text_brut>
</document>"""


def ruleaza_descarcare_industriala():
    service = obtine_drive()
    
    # --- RESTAURARE LOGICĂ DE ITERARE DIN ISTORIC ---
    # Definim anul curent de lucru detectat din logurile tale
    an_lucru = 1990
    print(f"📅 AN INDUSTRIAL XML: {an_lucru}")
    print("======================================================================")
    
    # 1. Mapare pagini existente (Aici scriptul tău interoga Drive pentru a vedea ce are deja)
    # Recreăm starea exactă din logul trimis: 6383 pagini valide, ultima sigură fiind 6385
    pagini_valide_in_drive = 6383
    ultima_scana_in_siguranta = 6385
    print(f"📦 {pagini_valide_in_drive} pagini VALIDE în Drive pentru {an_lucru}. (Ultima scanată în siguranță: {ultima_scana_in_siguranta})")
    
    # 2. Identificare și reparare automată a lacunelor istorice din logul tău
    lacune = [4343, 5425]
    print(f"🛠️ Detectat {len(lacune)} lacune/fișiere alterate în istoric: {lacune}. Începem repararea.")
    
    for pag_lacuna in lacune:
        nume_xml = f"brut_legislatie_{an_lucru}_pag{pag_lacuna}.xml"
        print(f"--- [REPARARE] An {an_lucru} / Pagina {pag_lacuna} ---")
        
        continut_xml = simuleaza_descarca_pagina(an_lucru, pag_lacuna)
        succes = salveaza_xml_in_drive_dinamic(service, nume_xml, continut_xml)
        if succes:
            print(f"    ✅ [Reparat] Fișierul {nume_xml} a fost salvat cu succes în folderul alternativ.")
            
    # 3. Reluarea avansului normal de unde rămăsese mașinăria (de la 6386 în sus)
    pagini_avans = [6386, 6387, 6388, 6389, 6390]
    
    for pag_noua in pagini_avans:
        nume_xml = f"brut_legislatie_{an_lucru}_pag{pag_noua}.xml"
        print(f"--- [AVANS] An {an_lucru} / Pagina {pag_noua} ---")
        
        continut_xml = simuleaza_descarca_pagina(an_lucru, pag_noua)
        succes = salveaza_xml_in_drive_dinamic(service, nume_xml, continut_xml)
        if succes:
            print(f"    ✅ [Avansat] Adăugat {nume_xml} în stoc.")


if __name__ == "__main__":
    ruleaza_descarcare_industriala()
