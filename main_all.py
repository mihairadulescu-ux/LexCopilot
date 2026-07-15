import os
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor

# URL-ul corect extras din structura WSDL-ului (se termină cu /basic)
URL_API = "http://legislatie.just.ro/apiws/FreeWebService.svc/basic"
FOLDER_DESCARCARE = "legi_xml_brut"
os.makedirs(FOLDER_DESCARCARE, exist_ok=True)

print_lock = threading.Lock()

def safe_print(message):
    with print_lock:
        print(message, flush=True)

def obtine_token_brut():
    """Obține token-ul printr-un apel POST SOAP simplu la endpoint-ul basic."""
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/GetToken"
    }
    
    # Plicul SOAP standard pentru a cere Token-ul
    soap_envelope = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tem="http://tempuri.org/">
       <soapenv:Header/>
       <soapenv:Body>
          <tem:GetToken/>
       </soapenv:Body>
    </soapenv:Envelope>"""
    
    try:
        safe_print("[🔑] Solicităm token nou...")
        response = requests.post(URL_API, data=soap_envelope, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Extragem token-ul direct din XML-ul primit
        text = response.text
        start = text.find("<GetTokenResult>") + len("<GetTokenResult>")
        end = text.find("</GetTokenResult>")
        
        if start != -1 and end != -1:
            token = text[start:end]
            safe_print(f"[🔑] Token primit cu succes: {token[:15]}...")
            return token
        else:
            safe_print("❌ Nu am găsit tag-ul <GetTokenResult> în răspunsul serverului.")
            safe_print(f"Răspuns primit: {text[:300]}")
    except Exception as e:
        safe_print(f"❌ Eroare la obținerea token-ului: {e}")
    return None

def descarca_pagina_xml(token, an, pagina, rezultate_per_pagina=50):
    """Trimite cererea de căutare și returnează XML-ul brut direct de pe rețea."""
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/Search"
    }
    
    # Plicul SOAP brut pentru căutare (SearchModel) conform schemei tempuri.org
    soap_envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tem="http://tempuri.org/" xmlns:leg="http://schemas.datacontract.org/2004/07/Legislatie.Just.Data.Models">
       <soapenv:Header/>
       <soapenv:Body>
          <tem:Search>
             <tem:SearchModel>
                <leg:NumarPagina>{pagina}</leg:NumarPagina>
                <leg:RezultatePagina>{rezultate_per_pagina}</leg:RezultatePagina>
                <leg:SearchAn>{an}</leg:SearchAn>
                <leg:SearchNumar></leg:SearchNumar>
                <leg:SearchText></leg:SearchText>
                <leg:SearchTitlu></leg:SearchTitlu>
             </tem:SearchModel>
             <tem:tokenKey>{token}</tem:tokenKey>
          </tem:Search>
       </soapenv:Body>
    </soapenv:Envelope>"""

    try:
        response = requests.post(URL_API, data=soap_envelope, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        safe_print(f"⚠️ [An {an}][Pagina {pagina}] Eroare la descărcare: {e}")
        return None

def crawleaza_an_complet(token, an):
    """Descarcă paginile rând pe rând pentru anul curent."""
    pagina = 0
    while True:
        safe_print(f"📥 [An {an}][Pagina {pagina}] Se descarcă...")
        
        xml_brut = descarca_pagina_xml(token, an, pagina)
        
        if not xml_brut:
            # Dacă serverul a dat eroare temporară de rețea, mai încercăm o dată înainte de a renunța
            time.sleep(2)
            xml_brut = descarca_pagina_xml(token, an, pagina)
            if not xml_brut:
                break
            
        # Verificăm dacă răspunsul este gol sau nu conține legi (semn că s-a terminat anul)
        if "<Legi />" in xml_brut or "<Legi>" not in xml_brut or "<Id>" not in xml_brut:
            safe_print(f"🛑 [An {an}] S-au terminat paginile la indexul {pagina}.")
            break
            
        # Salvăm fișierul XML brut pe disk exact așa cum a venit
        nume_fisier = os.path.join(FOLDER_DESCARCARE, f"an_{an}_pag_{pagina}.xml")
        with open(nume_fisier, "w", encoding="utf-8") as f:
            f.write(xml_brut)
            
        safe_print(f"💾 [An {an}][Pagina {pagina}] XML salvat.")
        pagina += 1
        
        # O mică pauză de 100ms ca să nu punem prea multă presiune deodată
        time.sleep(0.1)

def porneste_crawler():
    token = obtine_token_brut()
    if not token:
        return
        
    ani_de_procesat = list(range(2000, 2020)) # Anii de descărcat: 2000 - 2019
    max_paralel = 4
    
    safe_print(f"📅 Interval ani: 2000 - 2019")
    safe_print(f"🚀 Pornim exact {max_paralel} descărcări în paralel...")
    
    with ThreadPoolExecutor(max_workers=max_paralel) as executor:
        # Folosim o funcție lambda curată pentru map-ul paralel
        executor.map(lambda an: crawleaza_an_complet(token, an), ani_de_procesat)

if __name__ == "__main__":
    porneste_crawler()
