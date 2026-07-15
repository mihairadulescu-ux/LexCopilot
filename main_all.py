import os
import io
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor

# Bibliotecile Google Client API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Biblioteca SOAP salvatoare
from suds.client import Client
from suds.sax.element import Element

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

class LegislatieJustClient:
    def __init__(self):
        safe_print("[🔑 Just] Inițializăm clientul SOAP și solicităm token nou...")
        self.url = URL_API
        # Dezactivăm cache-ul suds pentru a evita conflictele la rulările repetate
        self.client = Client(self.url, cache=None)
        # Obținerea token-ului în mod nativ
        self.token = self.client.service.GetToken()
        safe_print(f"[🔑 Just] Token primit cu succes: {self.token[:15]}...")

    def obtine_pagina_xml_brut(self, an, pagina, rezultate_per_pagina=50):
        """
        Aici facem un mic truc de magie:
        Pentru că vrem să salvăm XML-ul brut (exact așa cum vine de la server) în Drive,
        interceptăm ultimul răspuns XML binar trimis de server, în loc să folosim obiectul Python parsat.
        """
        search_model = self.client.factory.create('SearchModel')
        search_model.NumarPagina = pagina
        search_model.RezultatePagina = rezultate_per_pagina
        search_model.SearchAn = an
        
        # Apelăm serviciul (asta va popula client.last_received())
        self.client.service.Search(search_model, self.token)
        
        # Extragem XML-ul brut primit la ultimul request
        xml_brut = self.client.last_received()
        if xml_brut:
            # Îl decodăm în string UTF-8 curat
            return str(xml_brut)
        return None

def crawleaza_an_complet(client, an):
    """Descarcă pagină cu pagină pentru anul dat folosind suds și le trimite în Shared Drive."""
    pagina = 0
    while True:
        safe_print(f"📥 [An {an}][Pagina {pagina}] Se descarcă de pe Just...")
        
        try:
            xml_brut = client.obtine_pagina_xml_brut(an, pagina)
        except Exception as e:
            safe_print(f"⚠️ [An {an}][Pagina {pagina}] Eroare la descărcare de pe Just: {e}. Reîncercăm peste 3 secunde...")
            time.sleep(3)
            try:
                xml_brut = client.obtine_pagina_xml_brut(an, pagina)
            except Exception:
                safe_print(f"❌ [An {an}][Pagina {pagina}] Eșec definitiv la descărcare.")
                break

        if not xml_brut:
            break
            
        # Verificăm în XML-ul brut dacă am ajuns la capătul listei de legi
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
        time.sleep(0.2)  # Delay fin de curtoazie pentru API

def porneste_crawler():
    # 1. Verificăm mai întâi Google Drive
    try:
        safe_print("[☁️] Se inițializează conexiunea cu Google Drive...")
        obtine_serviciu_drive()
        safe_print("[☁️] Conexiune la Shared Drive realizată cu succes!")
    except Exception as e:
        safe_print(f"❌ Conexiunea la Google Drive a eșuat: {e}")
        return

    # 2. Inițializăm clientul SOAP Just (fiecare thread va folosi acest client în siguranță)
    try:
        client_just = LegislatieJustClient()
    except Exception as e:
        safe_print(f"❌ Nu s-a putut inițializa clientul LegislatieJust: {e}")
        return
        
    ani_de_procesat = list(range(AN_START, AN_STOP + 1))
    max_paralel = 4  # Număr ideal de conexiuni SOAP simultane
    
    safe_print(f"📅 Interval ani selectat: {AN_START} - {AN_STOP}")
    safe_print(f"🚀 Pornim cele {max_paralel} descărcări paralele direct către Shared Drive...")
    
    with ThreadPoolExecutor(max_workers=max_paralel) as executor:
        # Trimitem clientul suds gata autentificat către fiecare thread
        executor.map(lambda an: crawleaza_an_complet(client_just, an), ani_de_procesat)

if __name__ == "__main__":
    porneste_crawler()
