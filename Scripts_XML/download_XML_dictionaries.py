# Culori pentru un log frumos în consolă
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

import os
import csv
import io
import json
from zeep import Client
from zeep.transports import Transport
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

# CONFIGURĂRI DINAMICE (PRELUATE DIN MEDIUL GITHUB ACTIONS)
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"
METADATA_FOLDER_ID = os.getenv("METADATA_FOLDER_ID")


def get_drive_service():
    """Autentifică robotul în Google Drive folosind GitHub Secrets sau local."""
    scopes = ["https://www.googleapis.com/auth/drive.file"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        print(f"{VERDE}🤖 [Cloud Mode] Autentificare în Google Drive folosind GitHub Secrets...{RESET}")
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        print(f"{GALBEN}💻 [Local Mode] Autentificare în Google Drive...{RESET}")
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul '{credentials_path}'!")
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        
    return build("drive", "v3", credentials=creds)


def upload_csv_to_drive(service, filename, csv_content_string):
    """Încarcă sau suprascrie fișierul CSV direct în folderul din Google Drive."""
    if not METADATA_FOLDER_ID:
        print(f"{ROSU}❌ Eroare: Variabila de mediu METADATA_FOLDER_ID nu este definită!{RESET}")
        return False

    try:
        content_bytes = csv_content_string.encode('utf-8')
        
        # Căutăm dacă fișierul există deja în folderul dedicat de metadate
        query = f"'{METADATA_FOLDER_ID}' in parents and name = '{filename}' and trashed = false"
        existing_files = service.files().list(q=query, spaces='drive', fields='files(id)', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        
        media = MediaInMemoryUpload(content_bytes, mimetype="text/csv", resumable=True)
        
        if existing_files:
            file_id = existing_files[0]['id']
            file = service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            print(f"{VERDE}🔄 [Update] Dicționar suprascris cu succes în Drive: {filename} (ID: {file.get('id')}){RESET}")
        else:
            file_metadata = {"name": filename, "parents": [METADATA_FOLDER_ID]}
            file = service.files().create(body=file_metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
            print(f"{VERDE}✅ [Nou] Dicționar salvat cu succes în Drive: {filename} (ID: {file.get('id')}){RESET}")
        return True
    except Exception as e:
        print(f"{ROSU}❌ Eroare upload Drive pentru {filename}: {e}{RESET}")
        return False


def create_fresh_soap_client():
    """Creează o instanță curată de client SOAP cu timeout extins."""
    transport = Transport(timeout=60, operation_timeout=90)
    return Client(WSDL_URL, transport=transport)


def descarca_nomenclatoare_xml_to_drive():
    print(f"{VERDE}🚀 Pornire descărcare dicționare de metadate XML direct în Google Drive...{RESET}\n")
    print(f"📂 Folder țintă Metadate ID: {METADATA_FOLDER_ID}")
    
    # Inițializare servicii
    try:
        drive_service = get_drive_service()
        soap_client = create_fresh_soap_client()
        token_key = soap_client.service.GetToken()
        print(f"{VERDE}✅ Autentificare reușită pe toate fronturile.{RESET}")
    except Exception as e:
        print(f"{ROSU}🛑 Eroare critică la inițializare: {e}{RESET}")
        return

    # ======================================================================
    # 🔍 DIAGNOSTIC: Listăm operațiunile reale expuse de Just.ro
    # ======================================================================
    print(f"\n{GALBEN}🔍 [DIAGNOSTIC] Inspectăm operațiunile disponibile în serviciul SOAP...{RESET}")
    try:
        for service in soap_client.wsdl.services.values():
            for port in service.ports.values():
                operations = port.binding._operations.keys()
                print(f"{VERDE}   -> Funcții disponibile pe portul '{port.name}':{RESET}")
                for op in sorted(operations):
                    print(f"      • {op}")
    except Exception as diag_err:
        print(f"{ROSU}⚠️ Nu am putut lista funcțiile: {diag_err}{RESET}")
    print(f"{GALBEN}{'='*70}{RESET}\n")

    # ======================================================================
    # 1. GENERARE & UPLOAD NOMENCLATOR EMITENȚI
    # ======================================================================
    print(f"\n⏳ Se interoghează serverul Just.ro pentru Emitenți...")
    try:
        # Încercăm apelul nativ. Dacă crapă, diagnosticul de mai sus ne va spune de ce.
        raspuns_emitenti = soap_client.service.GetEmitenti(tokenKey=token_key)
        
        if raspuns_emitenti and hasattr(raspuns_emitenti, 'Emitent'):
            lista_emitenti = raspuns_emitenti.Emitent
            
            output = io.StringIO()
            writer = csv.writer(output, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(["ID", "Denumire"])
            
            contor = 0
            for emitent in lista_emitenti:
                emitent_id = getattr(emitent, 'Id', '')
                emitent_nume = getattr(emitent, 'Denumire', '')
                writer.writerow([emitent_id, emitent_nume])
                contor += 1
                
            upload_csv_to_drive(drive_service, "dictionar_emitenti.csv", output.getvalue())
            print(f"{VERDE}📊 Total Emitenți procesați: {contor}{RESET}")
        else:
            print(f"{GALBEN}⚠️ Răspuns gol primit de la server pentru Emitenți.{RESET}")
    except Exception as e:
        print(f"{ROSU}❌ Eroare la procesarea dicționarului de Emitenți: {e}{RESET}")

    # ======================================================================
    # 2. GENERARE & UPLOAD NOMENCLATOR TIP ACTE
    # ======================================================================
    print(f"\n⏳ Se interoghează serverul Just.ro pentru Tip Acte...")
    try:
        raspuns_tip_acte = soap_client.service.GetTipActe(tokenKey=token_key)
        
        if raspuns_tip_acte and hasattr(raspuns_tip_acte, 'TipAct'):
            lista_tip_acte = raspuns_tip_acte.TipAct
            
            output = io.StringIO()
            writer = csv.writer(output, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(["ID", "Denumire", "GrupActID"])
            
            contor = 0
            for tip_act in lista_tip_acte:
                act_id = getattr(tip_act, 'Id', '')
                act_nume = getattr(tip_act, 'Denumire', '')
                act_grup = getattr(tip_act, 'IdGrupAct', '')
                writer.writerow([act_id, act_nume, act_grup])
                contor += 1
                
            upload_csv_to_drive(drive_service, "dictionar_tip_acte.csv", output.getvalue())
            print(f"{VERDE}📊 Total Tip Acte procesate: {contor}{RESET}")
        else:
            print(f"{GALBEN}⚠️ Răspuns gol primit de la server pentru Tip Acte.{RESET}")
    except Exception as e:
        print(f"{ROSU}❌ Eroare la procesarea dicționarului de Tip Acte: {e}{RESET}")

    print(f"\n{VERDE}🎉 Procesul s-a încheiat! Verifică logurile de mai sus pentru lista de funcții.{RESET}")


if __name__ == "__main__":
    os.environ["PYTHONUNBUFFERED"] = "1"
    descarca_nomenclatoare_xml_to_drive()
