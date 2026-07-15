import os
import io
import time
import random
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from pathlib import Path

# Librării SOAP și Google API
from zeep import Client, Settings
from zeep.exceptions import Fault
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ======================================================================
# ⚙️ CONFIGURARE
# ======================================================================
WSDL_URL = 'http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl'
AN_START = 2000
AN_STOP = 2019
MAX_THREADS = 4

# ID-ul folderului tău shared Google Drive primit
GDRIVE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"

# ======================================================================
# 🔑 CLIENT GOOGLE DRIVE (Autentificare automată în GitHub)
# ======================================================================
def obtine_serviciu_gdrive():
    """Inițializează clientul Google Drive folosind secretele din mediu."""
    # În GitHub Actions, este recomandat să salvezi JSON-ul cheii într-un Secret (ex: GDRIVE_CREDENTIALS)
    cheie_json = os.environ.get("GDRIVE_CREDENTIALS")
    
    if cheie_json:
        # Dacă secretul este stocat ca string JSON brut în variabilele de mediu
        import json
        info = json.loads(cheie_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive.file']
        )
    else:
        # Căutare fallback locală/manuală dacă rulezi pe local
        cale_cheie_locala = Path("credentials.json")
        if cale_cheie_locala.exists():
            creds = service_account.Credentials.from_service_account_file(
                str(cale_cheie_locala), scopes=['https://www.googleapis.com/auth/drive.file']
            )
        else:
            raise RuntimeError(
                "❌ Nu s-au găsit credențialele Google Drive! "
                "Asigură-te că ai setat variabila de mediu GDRIVE_CREDENTIALS sau fișierul credentials.json."
            )
            
    return build('drive', 'v3', credentials=creds)


# ======================================================================
# 🔒 MANAGER TOKEN SOAP (Thread-Safe)
# ======================================================================
class TokenManager:
    def __init__(self, client):
        self.client = client
        self.token = None
        self.lock = Lock()

    def get_valid_token(self, forta_reproaspatare=False):
        with self.lock:
            if self.token is None or forta_reproaspatare:
                if forta_reproaspatare:
                    print("\n[🔑] Tokenul a expirat. Generăm unul nou...")
                else:
                    print("\n[🔑] Inițializare: Obținem token nou pentru Portalul Legislativ...")
                
                while True:
                    try:
                        self.token = self.client.service.GetToken()
                        if self.token:
                            print(f"[🔑] Token generat cu succes: {self.token[:10]}...")
                            break
                    except Exception as e:
                        print(f"[⚠️] Serverul Just ocupat ({e}). Reîncercăm în 3 secunde...")
                        time.sleep(3)
            return self.token

# ======================================================================
# 📤 LOGICĂ DE SALVARE ÎN GOOGLE DRIVE
# ======================================================================
def incarca_in_gdrive(service, nume_fisier, continut_text):
    """Încarcă un fișier text direct în folderul shared Google Drive, fără salvare locală."""
    file_metadata = {
        'name': nume_fisier,
        'parents': [GDRIVE_FOLDER_ID]
    }
    
    # Transformăm textul în stream de octeți în memorie
    fh = io.BytesIO(continut_text.encode('utf-8'))
    media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=True)
    
    # Trimitem fișierul la Google Drive API (suportă drive-uri partajate prin supportsAllDrives)
    service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id',
        supportsAllDrives=True  # Important pentru Shared Drive
    ).execute()

# ======================================================================
# 🚀 PROCESATOR AN (Rulat în paralel)
# ======================================================================
def proceseaza_an(an, token_manager, client, gdrive_service):
    """Descarcă legislația unui an și o trimite direct în Google Drive."""
    pagina = 0
    rezultate_pe_pagina = 50
    token = token_manager.get_valid_token()
    
    while True:
        search_params = {
            'NumarPagina': pagina,
            'RezultatePagina': rezultate_pe_pagina,
            'SearchAn': an,
        }
        
        try:
            response = client.service.Search(search_params, token)
            
            if response and hasattr(response, 'Legi') and response.Legi:
                lista_legi = response.Legi.Legi
                if not lista_legi:
                    print(f"✅ [An {an}] Finalizat complet.")
                    break
                
                # Construim structura fișierului în memorie
                buffer_text = []
                for lege in lista_legi:
                    buffer_text.append(f"ID: {lege.IdValoare} | Titlu: {lege.Titlu} | Data: {lege.DataVigoare}")
                
                continut_final = "\n".join(buffer_text)
                nume_fisier_gdrive = f"legi_{an}_pag_{pagina}.txt"
                
                # Încărcare direct în folderul shared Google Drive
                incarca_in_gdrive(gdrive_service, nume_fisier_gdrive, continut_final)
                
                print(f"☁️ [An {an}] Pagina {pagina} salvată direct în GDrive ({len(lista_legi)} acte).")
                pagina += 1
                
                time.sleep(random.uniform(0.3, 0.6))
                
            else:
                print(f"ℹ️ [An {an}] S-a atins capătul listei la pagina {pagina}.")
                break
                
        except Fault as soap_fault:
            fault_string = str(soap_fault).lower()
            if "token" in fault_string or "expired" in fault_string or "invalid" in fault_string:
                token = token_manager.get_valid_token(forta_reproaspatare=True)
            else:
                print(f"❌ [An {an}] Eroare SOAP (Pagina {pagina}): {soap_fault}")
                time.sleep(5)
                
        except Exception as e:
            print(f"⚠️ [An {an}] Reîncercare din cauza unei erori la pagina {pagina}: {e}")
            time.sleep(5)

# ======================================================================
# 🏁 FLUX PRINCIPAL
# ======================================================================
def main():
    print("🚀 Pornire Crawler Just.ro + integrare Google Drive API...")
    
    # 1. Inițializăm serviciul Google Drive
    try:
        gdrive_service = obtine_serviciu_gdrive()
        print("🔓 Conexiune la Google Drive stabilită cu succes.")
    except Exception as e:
        print(f"💥 Eroare critică la inițializarea Google Drive: {e}")
        sys.exit(1)

    # 2. Inițializăm clientul SOAP Zeep
    settings = Settings(strict=False, xml_huge_tree=True)
    client = Client(WSDL_URL, settings=settings)
    
    token_manager = TokenManager(client)
    ani_de_procesat = list(range(AN_START, AN_STOP + 1))
    
    print(f"📅 Interval ani: {AN_START} - {AN_STOP}")
    print(f"🧵 Thread-uri active: {MAX_THREADS}\n")
    
    # 3. Rulăm pool-ul de thread-uri în paralel
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = [
            executor.submit(proceseaza_an, an, token_manager, client, gdrive_service) 
            for an in ani_de_procesat
        ]
        for future in futures:
            future.result()

    print("\n🏁 Gata! Toate legile au fost colectate și urcate direct în folderul tău din Google Drive.")

if __name__ == '__main__':
    main()
