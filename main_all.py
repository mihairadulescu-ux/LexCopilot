import os
import io
import json
import time
import threading
import subprocess
import sys

# --- AUTO-INSTALARE SUDS DACĂ LIPSEȘTE (SIGURANȚĂ DUBLĂ) ---
try:
    from suds.client import Client
except ImportError:
    print("[📦 System] Biblioteca 'suds-py3' nu a fost găsită. O instalăm acum...", flush=True)
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "suds-py3"])
        from suds.client import Client
        print("[📦 System] 'suds-py3' a fost instalată cu succes!", flush=True)
    except Exception as e:
        print(f"❌ Nu s-a putut instala automat 'suds-py3': {e}", flush=True)
        sys.exit(1)
# ------------------------------------------------------------

from concurrent.futures import ThreadPoolExecutor

# Bibliotecile Google Client API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==================== CONFIGURĂRI PARAMETRI ====================
URL_API = 'http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl'
GOOGLE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"

AN_START = 2000
AN_STOP = 2019
# ===============================================================

print_lock = threading.Lock()
drive_service_lock = threading.Lock()
_drive_service = None

def safe_print(message):
    with print_lock:
        print(message, flush=True)

def obtine_serviciu_drive():
    """Inițializează serviciul Google Drive (Thread-Safe) conform configurării tale."""
    global _drive_service
    with drive_service_lock:
        if _drive_service is not None:
            return _drive_service

        sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not sa_json:
            raise ValueError("❌ Lipseste variabila de mediu GOOGLE_SERVICE_ACCOUNT_JSON!")
        
        creds_info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_info, 
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        
        _drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        return _drive_service

def incarca_in_google_drive(continut_xml, nume_fisier):
    """Încarcă fișierul XML în Shared Drive-ul Corporate."""
    try:
        service = obtine_serviciu_drive()
        
        metadata_fisier = {
            'name': nume_fisier,
            'parents': [GOOGLE_FOLDER_ID]
        }
        
        fh = io.BytesIO(continut_xml.encode('utf-8'))
        media = MediaIoBaseUpload(fh, mimetype='text/xml', resumable=True)
        
        file = service.files().create(
            body=metadata_fisier,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        
        return file.get('id')
    except Exception as e:
        safe_print(f"❌ Eroare Google Drive la încărcarea {nume_fisier}: {e}")
        return None

def obtine_token_sesiune():
    """Obține un singur token valid pe care îl vom partaja între toate thread-urile."""
    try:
        safe_print("[🔑 Just] Inițializăm un client SOAP temporar pentru a cere token-ul general...")
        client_temp = Client(URL_API, cache=None)
        token = client_temp.service.GetToken()
        safe_print(f"[🔑 Just] Token generat cu succes pentru sesiune: {token[:15]}...")
        return token
    except Exception as e:
        safe_print(f"❌ Nu s-a putut obține token-ul legislativ: {e}")
        return None

def descarca_si_incarca_pagina(client_soap, token, an, pagina):
    """
    Descarcă pagina prin SOAP folosind clientul dedicat al thread-ului actual,
    apoi urcă rezultatul direct în Google Drive.
    """
    search_model = client_soap.factory.create('SearchModel')
    search_model.NumarPagina = pagina
    search_model.RezultatePagina = 50
    search_model.SearchAn = an
    
    # Executăm căutarea prin SOAP
    client_soap.service.Search(search_model, token)
    
    # Interceptăm XML-ul brut sosit special pe această instanță de client (complet Thread-Safe!)
    xml_brut = client_soap.last_received()
    if not xml_brut:
        return None
    
    return str(xml_brut)

def crawleaza_an_complet(token, an):
    """
    Fiecare thread își creează propriul său client SOAP ne-partajat (Thread-Safe)
    pentru a evita ca răspunsurile XML să se amestece între ani.
    """
    safe_print(f"🔄 [An {an}] Pornire descărcare. Se inițializează clientul SOAP dedicat...")
    try:
        client_soap_dedicat = Client(URL_API, cache=None)
    except Exception as e:
        safe_print(f"❌ [An {an}] Nu s-a putut crea clientul SOAP dedicat: {e}")
        return

    pagina = 0
    while True:
        safe_print(f"📥 [An {an}][Pagina {pagina}] Se descarcă de pe Just...")
        
        try:
            xml_brut = descarca_si_incarca_pagina(client_soap_dedicat, token, an, pagina)
        except Exception as e:
            safe_print(f"⚠️ [An {an}][Pagina {pagina}] Eroare temporară: {e}. Reîncercăm peste 4 secunde...")
            time.sleep(4)
            try:
                xml_brut = descarca_si_incarca_pagina(client_soap_dedicat, token, an, pagina)
            except Exception:
                safe_print(f"❌ [An {an}][Pagina {pagina}] Eșec definitiv la descărcare.")
                break

        if not xml_brut:
            break
            
        # Verificăm dacă am terminat paginile cu legi
        if "<Legi />" in xml_brut or "<Legi" not in xml_brut or "<Id>" not in xml_brut:
            safe_print(f"🛑 [An {an}] S-au terminat paginile la indexul {pagina}.")
            break
            
        nume_fisier = f"an_{an}_pag_{pagina}.xml"
        drive_file_id = incarca_in_google_drive(xml_brut, nume_fisier)
        
        if drive_file_id:
            safe_print(f"☁️ [An {an}][Pagina {pagina}] Salvat cu succes în Shared Drive! ID: {drive_file_id[:10]}...")
        else:
            safe_print(f"❌ [An {an}][Pagina {pagina}] Eșec la salvarea în Shared Drive.")
            
        pagina += 1
        time.sleep(0.2)  # Pauză fină pentru a menține conexiunea curată

def porneste_crawler():
    # 1. Test conexiune Google Drive
    try:
        safe_print("[☁️] Se inițializează conexiunea cu Google Drive...")
        obtine_serviciu_drive()
        safe_print("[☁️] Conexiune la Shared Drive realizată cu succes!")
    except Exception as e:
        safe_print(f"❌ Conexiunea la Google Drive a eșuat: {e}")
        return

    # 2. Obținem un token de sesiune
    token = obtine_token_sesiune()
    if not token:
        return
        
    ani_de_procesat = list(range(AN_START, AN_STOP + 1))
    max_paralel = 4  # Conexiuni paralele optime pentru a nu bloca IP-ul
    
    safe_print(f"📅 Interval ani selectat: {AN_START} - {AN_STOP}")
    safe_print(f"🚀 Pornim cele {max_paralel} descărcări paralele direct către Shared Drive...")
    
    with ThreadPoolExecutor(max_workers=max_paralel) as executor:
        executor.map(lambda an: crawleaza_an_complet(token, an), ani_de_procesat)

if __name__ == "__main__":
    porneste_crawler()
