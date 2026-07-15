import os
import io
import json
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor

# Bibliotecile Google Client API
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account

# Configurări API Just și Google Drive
URL_API = "http://legislatie.just.ro/apiws/FreeWebService.svc/SOAP"  # Endpoint fizic SOAP
GOOGLE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"
SCOPES = ['https://www.googleapis.com/auth/drive.file']

print_lock = threading.Lock()
drive_service_lock = threading.Lock()
_drive_service = None

def safe_print(message):
    with print_lock:
        print(message, flush=True)

def obtine_serviciu_drive():
    """
    Inițializează serviciul Google Drive (Thread-Safe) folosind 
    cheia secretă din variabila de mediu, evitând scrierea pe disc.
    """
    global _drive_service
    with drive_service_lock:
        if _drive_service is not None:
            return _drive_service

        creds = None
        
        # Încercăm să citim cheia secretă din variabila de mediu (recomandat pentru GitHub/CI-CD)
        secret_env = os.environ.get("GDRIVE_SERVICE_ACCOUNT_KEY")
        
        if secret_env:
            try:
                # Parsăm JSON-ul direct din string-ul din variabila de mediu
                info = json.loads(secret_env)
                creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
                safe_print("[🔑 GDrive] Credențiale încărcate cu succes din variabila de mediu.")
            except Exception as e:
                safe_print(f"❌ Eroare la parsarea variabilei de mediu GDRIVE_SERVICE_ACCOUNT_KEY: {e}")
        
        # Fallback local (dacă testezi local și ai fișierul fizic)
        if not creds and os.path.exists('service_account.json'):
            creds = service_account.Credentials.from_service_account_file(
                'service_account.json', scopes=SCOPES
            )
            safe_print("[🔑 GDrive] Credențiale încărcate din fișierul local service_account.json.")

        if not creds:
            raise Exception(
                "❌ Lipsesc credențialele Google Drive! Asigură-te că ai setat variabila de mediu "
                "GDRIVE_SERVICE_ACCOUNT_KEY sau că ai fișierul local 'service_account.json'."
            )

        _drive_service = build('drive', 'v3', credentials=creds)
        return _drive_service

def incarca_in_google_drive(continut_text, nume_fisier):
    """
    Încarcă textul XML ca fișier direct în folderul din Shared Drive Corporate.
    """
    try:
        service = obtine_serviciu_drive()
        
        metadata_fisier = {
            'name': nume_fisier,
            'parents': [GOOGLE_FOLDER_ID]
        }
        
        fh = io.BytesIO(continut_text.encode('utf-8'))
        media = MediaIoBaseUpload(fh, mimetype='text/xml', resumable=True)
        
        # Apel optimizat special pentru volume corporate (Shared Drive)
        file = service.files().create(
            body=metadata_fisier,
            media_body=media,
            fields='id',
            supportsAllDrives=True  # Parametrul critic care permite scrierea pe unități partajate
        ).execute()
        
        return file.get('id')
    except Exception as e:
        safe_print(f"❌ Eroare Google Drive la încărcarea {nume_fisier}: {e}")
        return None

def obtine_token_brut():
    """Obține token-ul legislativ printr-un apel POST SOAP valid."""
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/GetToken"
    }
    
    soap_envelope = """<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Header>
    <Action s:mustUnderstand="1" xmlns="http://schemas.microsoft.com/ws/2005/05/addressing/none">http://tempuri.org/IFreeWebService/GetToken</Action>
  </s:Header>
  <s:Body>
    <GetToken xmlns="http://tempuri.org/" />
  </s:Body>
</s:Envelope>"""
    
    try:
        safe_print("[🔑 Just] Solicităm token nou legislativ...")
        response = requests.post(URL_API, data=soap_envelope, headers=headers, timeout=15)
        response.raise_for_status()
        
        text = response.text
        start = text.find("<GetTokenResult>") + len("<GetTokenResult>")
        end = text.find("</GetTokenResult>")
        
        if start != -1 and end != -1:
            token = text[start:end]
            safe_print(f"[🔑 Just] Token primit: {token[:15]}...")
            return token
        else:
            safe_print("❌ Nu am găsit tag-ul <GetTokenResult> în XML-ul returnat.")
    except Exception as e:
        safe_print(f"❌ Eroare la obținerea token-ului legislativ: {e}")
    return None

def descarca_pagina_xml(token, an, pagina, rezultate_per_pagina=50):
    """Trimite interogarea SOAP de căutare legislativă."""
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/Search"
    }
    
    soap_envelope = f"""<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Header>
    <Action s:mustUnderstand="1" xmlns="http://schemas.microsoft.com/ws/2005/05/addressing/none">http://tempuri.org/IFreeWebService/Search</Action>
  </s:Header>
  <s:Body>
    <Search xmlns="http://tempuri.org/">
      <SearchModel xmlns:d4p1="http://schemas.datacontract.org/2004/07/FreeWebService" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
        <d4p1:NumarPagina>{pagina}</d4p1:NumarPagina>
        <d4p1:RezultatePagina>{rezultate_per_pagina}</d4p1:RezultatePagina>
        <d4p1:SearchAn>{an}</d4p1:SearchAn>
        <d4p1:SearchNumar i:nil="true" />
        <d4p1:SearchText i:nil="true" />
        <d4p1:SearchTitlu i:nil="true" />
      </SearchModel>
      <tokenKey>{token}</tokenKey>
    </Search>
  </s:Body>
</s:Envelope>"""

    try:
        response = requests.post(URL_API, data=soap_envelope, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        safe_print(f"⚠️ [An {an}][Pagina {pagina}] Eroare la descărcare de pe serverul legislativ: {e}")
        return None

def crawleaza_an_complet(token, an):
    """Descarcă pagină cu pagină și le urcă asincron în Google Drive."""
    pagina = 0
    while True:
        safe_print(f"📥 [An {an}][Pagina {pagina}] Se descarcă de pe Just...")
        
        xml_brut = descarca_pagina_xml(token, an, pagina)
        
        if not xml_brut:
            time.sleep(2)
            xml_brut = descarca_pagina_xml(token, an, pagina)
            if not xml_brut:
                break
            
        # Dacă XML-ul nu conține legi, am terminat anul respectiv
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
        time.sleep(0.15)  # Pauză mică pentru politică de bun simț față de API-ul Just

def porneste_crawler():
    # Inițializăm mai întâi clientul de Drive ca să fim siguri că secretele sunt bune
    try:
        safe_print("[☁️] Se inițializează conexiunea cu Google Drive...")
        obtine_serviciu_drive()
        safe_print("[☁️] Conexiune la Shared Drive realizată cu succes!")
    except Exception as e:
        safe_print(f"❌ Nu s-a putut porni crawler-ul deoarece conexiunea la Google Drive a eșuat: {e}")
        return

    token = obtine_token_brut()
    if not token:
        return
        
    ani_de_procesat = list(range(2000, 2020))  # Descarcă intervalul de ani 2000 - 2019
    max_paralel = 4
    
    safe_print(f"📅 Interval ani: 2000 - 2019")
    safe_print(f"🚀 Pornim exact {max_paralel} descărcări în paralel cu salvare directă în Shared Drive...")
    
    with ThreadPoolExecutor(max_workers=max_paralel) as executor:
        executor.map(lambda an: crawleaza_an_complet(token, an), ani_de_procesat)

if __name__ == "__main__":
    porneste_crawler()
