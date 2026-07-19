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
    Încearcă să salveze fișierul XML în primul folder disponibil din listă.
    Dacă folderul este plin (teamDriveFileLimitExceeded sau 403), trece automat
    și transparent la următorul ID, asigurând continuitatea workflow-ului.
    """
    if not FOLDER_IDS:
        print(f"{ROSU}🛑 Eroare: Nu s-a găsit niciun ID de folder valid în DRIVE_FOLDER_XML!{RESET}")
        return False

    for folder_id in FOLDER_IDS:
        try:
            # Structura fișierului pentru Google Drive API
            file_metadata = {
                'name': nume_fisier,
                'parents': [folder_id]
            }
            
            # Configurăm stream-ul cu suport de tip resumable=True (prinde erorile în timpul transmisiei chunk-urilor)
            media = MediaIoBaseUpload(
                io.BytesIO(continut_xml.encode('utf-8')), 
                mimetype='text/xml',
                resumable=True
            )
            
            # Executăm upload-ul efectiv în Google Drive
            file_uploaded = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id',
                supportsAllDrives=True
            ).execute()
            
            # Dacă am ajuns aici, upload-ul a reușit! Ieșim din buclă și returnăm ID-ul fișierului.
            return file_uploaded.get('id')
            
        except Exception as e:
            # Interceptăm orice eroare generală sau HttpError generată de protocolul resumable
            eroare_text = str(e).lower()
            
            # Verificăm dacă este vorba de limită numerică de fișiere, spațiu plin sau eroare 403
            if "limit" in eroare_text or "exceeded" in eroare_text or "403" in eroare_text or "storage" in eroare_text:
                print(f"{GALBEN}⚠️ [Folder Plin/Limită Atingă] ID-ul {folder_id} a respins fișierul.{RESET}")
                print(f"{VERDE}▶️ Comutare automată și transparentă către următorul folder din listă...{RESET}")
                continue  # 'continue' ignoră restul blocului curent și trece imediat la următorul folder_id
            else:
                # Pentru alte erori neprevăzute, încercăm totuși să comutăm pentru a nu bloca rularea
                print(f"{ROSU}❌ Eroare la folderul {folder_id}: {e}{RESET}")
                continue
                
    print(f"{ROSU}🛑 EROARE CRITICĂ: Toate folderele din listă sunt pline sau inaccesibile!{RESET}")
    return False


def executa_procesare_legislatie():
    """
    Funcția principală care simulează sau gestionează logica ta de iterație pe ani și pagini.
    Aici se apelează funcția de salvare dinamică.
    """
    print(f"{VERDE}🚀 Pornire procesare și monitorizare volume de stocare XML...{RESET}")
    service = obtine_drive()
    
    # --- LOGICA TA EXISTENTĂ DE BUCLĂ (ANI / PAGINI / LACUNE) VINE AICI ---
    # Exemplu de integrare în interiorul buclei tale:
    # 
    # nume_xml = "brut_legislatie_1990_pag6386.xml"
    # continut_xml_generat = "<xml>...</xml>"
    #
    # print(f"--- [AVANS] An 1990 / Pagina 6386 ---")
    # succes = salveaza_xml_in_drive_dinamic(service, nume_xml, continut_xml_generat)
    # if not succes:
    #     print("❌ Eșec total la salvare pe toate locațiile.")
    # ---------------------------------------------------------------------


if __name__ == "__main__":
    executa_procesare_legislatie()
