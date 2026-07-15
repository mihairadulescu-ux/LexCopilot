import os
import io
import json
import time
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

_drive_service = None

def obtine_serviciu_drive():
    """Inițializează serviciul Google Drive (Secvențial)."""
    global _drive_service
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
        print(f"❌ Eroare Google Drive la încărcarea {nume_fisier}: {e}", flush=True)
        return None

def descarca_pagina_direct(client_soap, token, an, pagina):
    """
    Trimite cererea SOAP și returnează direct rezultatul apelului.
    """
    search_model = client_soap.factory.create('SearchModel')
    search_model.NumarPagina = pagina
    search_model.RezultatePagina = 50
    search_model.SearchAn = an
    
    # Executăm apelul SOAP și salvăm direct rezultatul
    rezultat = client_soap.service.Search(search_model, token)
    return rezultat

def crawleaza_an_complet(client_soap, token, an):
    """Parcurge pagină cu pagină pentru un singur an, complet secvențial."""
    pagina = 0
    while True:
        print(f"📥 [An {an}][Pagina {pagina}] Se descarcă de pe Just...", flush=True)
        
        try:
            raspuns = descarca_pagina_direct(client_soap, token, an, pagina)
        except Exception as e:
            print(f"⚠️ [An {an}][Pagina {pagina}] Eroare: {e}. Reîncercăm peste 5 secunde...", flush=True)
            time.sleep(5)
            try:
                raspuns = descarca_pagina_direct(client_soap, token, an, pagina)
            except Exception:
                print(f"❌ [An {an}][Pagina {pagina}] Eșec definitiv la descărcare.", flush=True)
                break

        # Convertim răspunsul în text indiferent de ce tip de obiect ne returnează suds
        xml_text = str(raspuns).strip()

        # --- DIAGNOZĂ SALVATOARE (Debug logs) ---
        print(f"🔍 [DEBUG An {an}] Tip răspuns: {type(raspuns)} | Lungime text: {len(xml_text)}", flush=True)
        if len(xml_text) > 0:
            # Afișăm primele 200 de caractere ca să vedem exact structura primită în consolă
            print(f"🔍 [DEBUG An {an}] Preview răspuns: {xml_text[:200]}...", flush=True)
        # ----------------------------------------

        # Verificăm dacă structura XML returnată conține date reale
        if not xml_text or "<Legi />" in xml_text or "<Legi" not in xml_text or "<Id>" not in xml_text:
            print(f"🛑 [An {an}] S-au terminat paginile sau structura nu este validă la indexul {pagina}.", flush=True)
            break
            
        nume_fisier = f"an_{an}_pag_{pagina}.xml"
        
        # Urcăm fișierul în Drive
        drive_file_id = incarca_in_google_drive(xml_text, nume_fisier)
        
        if drive_file_id:
            print(f"☁️ [An {an}][Pagina {pagina}] Salvat în Shared Drive! ID: {drive_file_id[:10]}...", flush=True)
        else:
            print(f"❌ [An {an}][Pagina {pagina}] Eșec la salvarea în Shared Drive.", flush=True)
            
        pagina += 1
        time.sleep(0.5)

def porneste_crawler():
    try:
        print("[☁️] Se inițializează conexiunea cu Google Drive...", flush=True)
        obtine_serviciu_drive()
        print("[☁️] Conexiune la Shared Drive realizată cu succes!", flush=True)
    except Exception as e:
        print(f"❌ Conexiunea la Google Drive a eșuat: {e}", flush=True)
        return

    try:
        print("[🔑 Just] Inițializăm clientul SOAP...", flush=True)
        client_soap = Client(URL_API, cache=None)
        
        print("[🔑 Just] Solicităm tokenul de sesiune...", flush=True)
        token = client_soap.service.GetToken()
        print(f"[🔑 Just] Token primit cu succes: {token[:15]}...", flush=True)
    except Exception as e:
        print(f"❌ Nu s-a putut conecta la serviciul Just: {e}", flush=True)
        return
        
    ani_de_procesat = list(range(AN_START, AN_STOP + 1))
    
    print(f"📅 Interval ani selectat: {AN_START} - {AN_STOP}", flush=True)
    print("🚀 Pornim descărcarea secvențială...", flush=True)
    
    for an in ani_de_procesat:
        crawleaza_an_complet(client_soap, token, an)
        time.sleep(0.5)

    print("✅ Descărcarea s-a încheiat cu succes pentru toți anii!", flush=True)

if __name__ == "__main__":
    porneste_crawler()
