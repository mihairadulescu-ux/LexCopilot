import os
import io
import time
import random
import sys
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

# Librării SOAP și Google API
from zeep import Client, Settings
from zeep.exceptions import Fault
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ======================================================================
# 🐛 ACTIVARE LOGGING BRUT SOAP (Pentru a vedea XML-ul exact în consolă)
# ======================================================================
logging.basicConfig(level=logging.INFO)
logging.getLogger('zeep.transports').setLevel(logging.DEBUG)  # Afișează XML-ul trimis/primit

# ======================================================================
# ⚙️ CONFIGURARE
# ======================================================================
WSDL_URL = 'http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl'
AN_START = 2000
AN_STOP = 2019
MAX_THREADS = 4

# ID-ul folderului tău shared Google Drive corporate
GDRIVE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"

# ======================================================================
# 🔑 CLIENT GOOGLE DRIVE (Autentificare)
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
    try:
        file_metadata = {
            'name': nume_fisier,
            'parents': [GDRIVE_FOLDER_ID]
        }
        fh = io.BytesIO(continut_text.encode('utf-8'))
        media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=True)
        
        service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True,
            keepRevisionForever=False
        ).execute()
    except Exception as e:
        print(f"❌ [GDrive Error] Nu s-a putut salva fișierul {nume_fisier}: {e}")

# ======================================================================
# 🚀 PROCESATOR AN
# ======================================================================
def proceseaza_an(an, token_manager, client, gdrive_service):
    """Descarcă legislația unui an și o trimite direct în Google Drive."""
    pagina = 0
    rezultate_pe_pagina = 50
    token = token_manager.get_valid_token()
    
    while True:
        # Trimitem structura respectând numele din WSDL
        search_model = {
            'NumarPagina': pagina,
            'RezultatePagina': rezultate_pe_pagina,
            'SearchAn': an,
            'SearchDomeniu': None,
            'SearchEmitent': None,
            'SearchModificata': None,
            'SearchNumar': None,
            'SearchRepublicata': None,
            'SearchText': None,
            'SearchTip': None,
            'SearchTitlu': None
        }
        
        print(f"\n🔍 [An {an}][Pagina {pagina}] Trimitem cerere cu parametrii: {search_model}")
        
        try:
            # Apel SOAP direct
            response = client.service.Search(SearchModel=search_model, tokenKey=token)
            
            # --- BLOC DE INSPECTARE INTERMEDIARĂ ---
            print(f"📊 [An {an}][Pagina {pagina}] Răspuns primit primit! Tip obiect răspuns: {type(response)}")
            if response is not None:
                # Afișăm atributele disponibile ale obiectului returnat ca să înțelegem ce structură are
                atribute = [attr for attr in dir(response) if not attr.startswith('_')]
                print(f"🔧 [An {an}][Pagina {pagina}] Atribute răspuns: {atribute}")
                
                # Verificăm direct ce conține proprietatea principală 'Legi'
                if hasattr(response, 'Legi'):
                    valoare_legi = getattr(response, 'Legi')
                    print(f"📦 [An {an}][Pagina {pagina}] Tipul câmpului response.Legi: {type(valoare_legi)}")
                    if valoare_legi is not None:
                        atribute_legi = [attr for attr in dir(valoare_legi) if not attr.startswith('_')]
                        print(f"📦 [An {an}][Pagina {pagina}] Atribute în response.Legi: {atribute_legi}")
            else:
                print(f"⚠️ [An {an}][Pagina {pagina}] Răspunsul primit este complet NULL (None)!")
            # ----------------------------------------

            lista_legi = None
            if response:
                # Încercăm să extragem datele pe baza structurii dinamice a Zeep
                if hasattr(response, 'Legi') and response.Legi is not None:
                    if isinstance(response.Legi, list):
                        lista_legi = response.Legi
                    elif hasattr(response.Legi, 'Legi') and isinstance(response.Legi.Legi, list):
                        lista_legi = response.Legi.Legi
                    else:
                        # Dacă e un singur element care nu e listă
                        lista_legi = [response.Legi]

                # Evaluăm rezultatul extragerii
                if lista_legi and len(lista_legi) > 0 and getattr(lista_legi[0], 'Titlu', None) is not None:
                    buffer_text = []
                    for lege in lista_legi:
                        id_val = getattr(lege, 'IdValoare', 'N/A')
                        tip_val = getattr(lege, 'TipAct', 'N/A')
                        numar_val = getattr(lege, 'Numar', 'N/A')
                        emitent_val = getattr(lege, 'Emitent', 'N/A')
                        data_val = getattr(lege, 'DataVigoare', 'N/A')
                        pub_val = getattr(lege, 'Publicatie', 'N/A')
                        titlu_val = getattr(lege, 'Titlu', 'Fără Titlu')
                        
                        buffer_text.append(
                            f"ID: {id_val} | Tip: {tip_val} | Nr: {numar_val} | "
                            f"Emitent: {emitent_val} | Data: {data_val} | "
                            f"Publicație: {pub_val} | Titlu: {titlu_val}"
                        )
                    
                    continut_final = "\n".join(buffer_text)
                    nume_fisier_gdrive = f"legi_{an}_pag_{pagina}.txt"
                    
                    # Salvare directă
                    incarca_in_gdrive(gdrive_service, nume_fisier_gdrive, continut_final)
                    
                    print(f"☁️ [An {an}] Pagina {pagina} salvată cu succes în Google Drive! ({len(lista_legi)} acte găsite)")
                    pagina += 1
                    time.sleep(random.uniform(0.8, 1.5))
                else:
                    print(f"✅ [An {an}] Finalizat complet la pagina {pagina}. `lista_legi` este goală sau invalidă.")
                    break
            else:
                print(f"ℹ️ [An {an}] Răspunsul de la server a fost gol la pagina {pagina}.")
                break
                
        except Fault as soap_fault:
            fault_string = str(soap_fault).lower()
            if "token" in fault_string or "expired" in fault_string or "invalid" in fault_string:
                token = token_manager.get_valid_token(forta_reproaspatare=True)
            else:
                print(f"❌ [An {an}] Eroare SOAP la Pagina {pagina}: {soap_fault}")
                time.sleep(5)
                
        except Exception as e:
            print(f"⚠️ [An {an}] Excepție neașteptată la pagina {pagina}: {e}")
            time.sleep(5)

# ======================================================================
# 🏁 FLUX PRINCIPAL
# ======================================================================
def main():
    print("🚀 Pornire Crawler Just.ro + Debugging SOAP activat...")
    
    # 1. Inițializăm serviciul Google Drive
    gdrive_service = obtine_serviciu_gdrive()
    print("🔓 Conexiune securizată la Google Drive realizată.")

    # 2. Inițializăm clientul SOAP Zeep cu logging
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

    print("\n🏁 Rulare încheiată. Verifică logurile de mai sus pentru diagnosticare completă!")

if __name__ == '__main__':
    main()
