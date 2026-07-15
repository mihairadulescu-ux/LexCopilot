import os
import io
import json
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor

# Bibliotecile Google Client API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==================== CONFIGURĂRI PARAMETRI ====================
# URL-ul oficial confirmat din ghid (cu cele 4 litere salvatoare la final)
URL_API = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

# ID-ul folderului tău din Shared Drive Corporate
GOOGLE_FOLDER_ID = "1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"

# INTERVALUL DE ANI PE CARE VREI SĂ ÎL DESCARCI
AN_START = 2000
AN_STOP = 2019  # Scriptul va descărca inclusiv anul de stop
# ===============================================================

print_lock = threading.Lock()
drive_service_lock = threading.Lock()
_drive_service = None

def safe_print(message):
    with print_lock:
        print(message, flush=True)

def obtine_serviciu_drive():
    """
    Inițializează serviciul Google Drive (Thread-Safe) folosind 
    exact metoda care funcționează deja în celelalte scripturi ale tale.
    """
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

def incarca_in_google_drive(continut_text, nume_fisier):
    """
    Încarcă XML-ul ca fișier direct în folderul specificat din Shared Drive-ul Corporate.
    """
    try:
        service = obtine_serviciu_drive()
        
        metadata_fisier = {
            'name': nume_fisier,
            'parents': [GOOGLE_FOLDER_ID]
        }
        
        fh = io.BytesIO(continut_text.encode('utf-8'))
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

def obtine_token_brut():
    """Obține token-ul legislativ printr-un apel SOAP conform documentației oficiale."""
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
    """Trimite cererea SOAP de căutare legislativă."""
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
    """Descarcă pagină cu pagină pentru anul dat și le trimite în Shared Drive."""
    pagina = 0
    while True:
        safe_print(f"📥 [An {an}][Pagina {pagina}] Se descarcă de pe Just...")
        
        xml_brut = descarca_pagina_xml(token, an, pagina)
        
        if not xml_brut:
            time.sleep(2)
            xml_brut = descarca_pagina_xml(token, an, pagina)
            if not xml_brut:
                break
            
        # Verificăm dacă am ajuns la capătul paginilor
        if "<Legi />" in xml_brut or "<Legi" not in xml_brut or "<Id>" not in xml_brut:
            safe_print(f"🛑 [An {an}] S-au terminat paginile la indexul {pagina}.")
            break
            
        nume_fisier = f"an_{an}_pag_{pagina}.xml"
        drive_file_id = incarca_in_google_drive(xml_brut, nume_fisier)
        
        if drive_file_id:
            safe_print(f"☁️ [An {an}][Pagina {pagina}] Salvat cu succes! ID: {drive_file_id[:10]}...")
        else:
            safe_print(f"❌ [An {an}][Pagina {pagina}] Eșec la salvarea în Shared Drive.")
            
        pagina += 1
        time.sleep(0.15)  # Mic delay de bun simț

def porneste_crawler():
    # Inițiem serviciul de Drive la pornire ca test de sănătate al cheii
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
        
    # Creăm lista de ani pe baza variabilelor de configurare globale
    # +1 ne asigură că includem și ultimul an setat în interval (ex: 2019)
    ani_de_procesat = list(range(AN_START, AN_STOP + 1))
    max_paralel = 4
    
    safe_print(f"📅 Interval ani selectat: {AN_START} - {AN_STOP}")
    safe_print(f"🚀 Pornim cele {max_paralel} descărcări paralele către Shared Drive...")
    
    with ThreadPoolExecutor(max_workers=max_paralel) as executor:
        executor.map(lambda an: crawleaza_an_complet(token, an), ani_de_procesat)

if __name__ == "__main__":
    porneste_crawler()
