import os
import io
import time
import random
import sys
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

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

# ID-ul folderului tău shared Google Drive
GDRIVE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"

# ======================================================================
# 🔑 CLIENT GOOGLE DRIVE (Autentificare strict prin GitHub Secrets)
# ======================================================================
def obtine_serviciu_gdrive():
    """Inițializează clientul Google Drive folosind secretul din mediul GitHub Actions."""
    cheie_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if not cheie_json:
        print("❌ EROARE CRITICĂ: Variabila GOOGLE_SERVICE_ACCOUNT_JSON nu este configurată în mediu!")
        sys.exit(1)
        
    try:
        info = json.loads(cheie_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ EROARE CRITICĂ la inițializarea credențialelor Google: {e}")
        sys.exit(1)


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
                    print("\n[🔑] Tokenul a expirat sau este invalid. Generăm unul nou...")
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
# 📤 LOGICĂ DE SALVARE ÎN GOOGLE DRIVE CORPORATE
# ======================================================================
def incarca_in_gdrive(service, nume_fisier, continut_text):
    """Încarcă un fișier text direct în folderul shared corporate Google Drive."""
    file_metadata = {
        'name': nume_fisier,
        'parents': [GDRIVE_FOLDER_ID]
    }
    
    # Pregătim textul în memorie ca stream de octeți
    fh = io.BytesIO(continut_text.encode('utf-8'))
    media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=True)
    
    # Parametri compleți pentru a ne asigura că este acceptat pe Shared Drive corporate
    service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id',
        supportsAllDrives=True,              # Permite crearea în Shared Drive corporate
        keepRevisionForever=False
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
        # Respectăm structura XML exactă din specificație utilizând un dicționar nativ,
        # lăsând Zeep să facă serializarea corectă a tipurilor opționale/nule.
        search_model = {
            'NumarPagina': pagina,
            'RezultatePagina': rezultate_pe_pagina,
            'SearchAn': an,
            'SearchNumar': None,
            'SearchText': None,
            'SearchTitlu': None
        }
        
        try:
            # Apelăm metoda Search cu denumirile exacte de parametri din WSDL: SearchModel și tokenKey
            response = client.service.Search(SearchModel=search_model, tokenKey=token)
            
            lista_legi = None
            if response:
                # Modificare critică de parsare: response (SearchResult) conține direct lista 'Legi'
                if hasattr(response, 'Legi') and response.Legi:
                    if isinstance(response.Legi, list):
                        lista_legi = response.Legi
                    elif hasattr(response.Legi, 'Legi') and response.Legi.Legi:
                        # Fallback în caz că structura XML se imbrivează în funcție de versiunea parserului local
                        lista_legi = response.Legi.Legi
                    else:
                        lista_legi = response.Legi

                # Dacă am identificat lista și conține elemente
                if lista_legi:
                    # Construim structura fișierului în memorie
                    buffer_text = []
                    for lege in lista_legi:
                        id_val = getattr(lege, 'IdValoare', 'N/A')
                        titlu_val = getattr(lege, 'Titlu', 'Fără Titlu')
                        data_val = getattr(lege, 'DataVigoare', 'Fără Dată')
                        emitent_val = getattr(lege, 'Emitent', 'Fără Emitent')
                        numar_val = getattr(lege, 'Numar', 'Fără Număr')
                        
                        buffer_text.append(
                            f"ID: {id_val} | "
                            f"Numar: {numar_val} | "
                            f"Emitent: {emitent_val} | "
                            f"Data: {data_val} | "
                            f"Titlu: {titlu_val}"
                        )
                    
                    continut_final = "\n".join(buffer_text)
                    nume_fisier_gdrive = f"legi_{an}_pag_{pagina}.txt"
                    
                    # Încărcare în GDrive corporate
                    incarca_in_gdrive(gdrive_service, nume_fisier_gdrive, continut_final)
                    
                    print(f"☁️ [An {an}] Pagina {pagina} salvată direct în GDrive ({len(lista_legi)} acte).")
                    pagina += 1
                    
                    # Delay politicos pentru a nu fi blocați de protecția firewall-ului Just
                    time.sleep(random.uniform(0.6, 1.2))
                    
                else:
                    print(f"✅ [An {an}] Finalizat complet (fără alte rezultate la pagina {pagina}).")
                    break
            else:
                print(f"ℹ️ [An {an}] Nu s-au întors date la pagina {pagina} (Răspuns gol).")
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
    print("🚀 Pornire Crawler Just.ro + integrare Google Drive API (Shared Drive Corporate)...")
    
    # 1. Inițializăm serviciul Google Drive
    gdrive_service = obtine_serviciu_gdrive()
    print("🔓 Conexiune securizată la Google Drive realizată.")

    # 2. Inițializăm clientul SOAP Zeep
    settings = Settings(strict=False, xml_huge_tree=True)
    client = Client(WSDL_URL, settings=settings)
    
    token_manager = TokenManager(client)
    ani_de_procesat = list(range(AN_START, AN_STOP + 1))
    
    print(f"📅 Interval ani selectat: {AN_START} - {AN_STOP}")
    print(f"🧵 Thread-uri active: {MAX_THREADS}\n")
    
    # 3. Pornim execuția paralelă pe ani
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = [
            executor.submit(proceseaza_an, an, token_manager, client, gdrive_service) 
            for an in ani_de_procesat
        ]
        for future in futures:
            future.result()

    print("\n🏁 Succes! Toate datele au fost colectate și urcate în Shared Drive-ul companiei.")

if __name__ == '__main__':
    main()
