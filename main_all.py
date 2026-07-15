import os
import io
import json
import time
import threading
import subprocess
import sys

# --- AUTO-INSTALARE SUDS DACĂ LIPSEȘTE ---
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
soap_client_lock = threading.Lock()  # Lock-ul salvator care previne coliziunile pe conexiunea SOAP
_drive_service = None

def safe_print(message):
    with print_lock:
        print(message, flush=True)

def obtine_serviciu_drive():
    """Inițializează serviciul Google Drive (Thread-Safe)."""
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

def descarca_pagina_safe(client_soap, token, an, pagina):
    """
    Folosește un singur client SOAP partajat, dar securizează apelul la nivel de rețea.
    Astfel, serverul Just.ro primește cererile pe rând, prevenind complet blocajele 503.
    """
    with soap_client_lock:
        search_model = client_soap.factory.create('SearchModel')
        search_model.NumarPagina = pagina
        search_model.RezultatePagina = 50
        search_model.SearchAn = an
        
        # Trimite request-ul SOAP
        client_soap.service.Search(search_model, token)
        
        # Obține XML-ul brut sosit special pentru acest request securizat
        xml_brut = client_soap.last_received()
        
        # O mică pauză de curtoazie (100ms) în interiorul lock-ului pentru a nu bombarda serverul Just
        time.sleep(0.1)
        
    if not xml_brut:
        return None
    return str(xml_brut)

def crawleaza_an_complet(client_soap, token, an):
    """Ciclează prin toate paginile anului primit."""
    pagina = 0
    while True:
        safe_print(f"📥 [An {an}][Pagina {pagina}] Se trimite cererea către Just...")
        
        try:
            xml_brut = descarca_pagina_safe(client_soap, token, an, pagina)
        except Exception as e:
            safe_print(f"⚠️ [An {an}][Pagina {pagina}] Eroare: {e}. Reîncercăm peste 5 secunde...")
            time.sleep(5)
            try:
                xml_brut = descarca_pagina_safe(client_soap, token, an, pagina)
            except Exception:
                safe_print(f"❌ [An {an}][Pagina {pagina}] Eșec definitiv la descărcare.")
                break

        if not xml_brut:
            break
            
        # Analizăm structura brută a răspunsului primit
        if "<Legi />" in xml_brut or "<Legi" not in xml_brut or "<Id>" not in xml_brut:
            safe_print(f"🛑 [An {an}] S-au terminat paginile la indexul {pagina}.")
            break
            
        nume_fisier = f"an_{an}_pag_{pagina}.xml"
        
        # Încărcarea în Drive rulează în afara lock-ului, deci este complet asincronă și rapidă!
        drive_file_id = incarca_in_google_drive(xml_brut, nume_fisier)
        
        if drive_file_id:
            safe_print(f"☁️ [An {an}][Pagina {pagina}] Salvat cu succes în Shared Drive! ID: {drive_file_id[:10]}...")
        else:
            safe_print(f"❌ [An {an}][Pagina {pagina}] Eșec la salvarea în Shared Drive.")
            
        pagina += 1

def porneste_crawler():
    # 1. Test conexiune Google Drive
    try:
        safe_print("[☁️] Se inițializează conexiunea cu Google Drive...")
        obtine_serviciu_drive()
        safe_print("[☁️] Conexiune la Shared Drive realizată cu succes!")
    except Exception as e:
        safe_print(f"❌ Conexiunea la Google Drive a eșuat: {e}")
        return

    # 2. Inițializare unică și controlată a clientului SOAP general
    try:
        safe_print("[🔑 Just] Inițializăm un singur client SOAP general (WSDL setup)...")
        client_soap_global = Client(URL_API, cache=None)
        
        safe_print("[🔑 Just] Solicităm tokenul de sesiune...")
        token = client_soap_global.service.GetToken()
        safe_print(f"[🔑 Just] Token primit cu succes: {token[:15]}...")
    except Exception as e:
        safe_print(f"❌ Nu s-a putut contacta serverul Just pentru inițializare: {e}")
        return
        
    ani_de_procesat = list(range(AN_START, AN_STOP + 1))
    max_paralel = 4  # Menținem pool-ul de thread-uri, dar apelurile de rețea Just vor fi sincronizate politicos
    
    safe_print(f"📅 Interval ani selectat: {AN_START} - {AN_STOP}")
    safe_print(f"🚀 Pornim motorul asincron de procesare...")
    
    with ThreadPoolExecutor(max_workers=max_paralel) as executor:
        executor.map(lambda an: crawleaza_an_complet(client_soap_global, token, an), ani_de_procesat)

if __name__ == "__main__":
    porneste_crawler()
