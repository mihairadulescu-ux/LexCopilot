import os
import time
import requests
import xml.etree.ElementTree as ET

# --- CODURI CULORI ANSI PENTRU CONSOLĂ ---
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

# --- URL ORIGINAL (HTTP) ---
WSDL_URL = "http://legislatie.just.ro/api/legis/LegislatieService.svc"

# User-Agent-ul de browser folosit anterior
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

CURRENT_TOKEN = None

def obtine_token_nou():
    """Apelează serviciul public pentru a genera un token nou."""
    global CURRENT_TOKEN
    print(f"{GALBEN}[-] Se încearcă conectarea la Just.ro pentru un token nou...{RESET}", flush=True)
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ILegislatieService/GetToken",
        "User-Agent": USER_AGENT
    }
    
    soap_request = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tem="http://tempuri.org/">
       <soapenv:Header/>
       <soapenv:Body>
          <tem:GetToken/>
       </soapenv:Body>
    </soapenv:Envelope>"""
    
    try:
        response = requests.post(WSDL_URL, data=soap_request, headers=headers, timeout=15)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            namespaces = {'s': 'http://schemas.xmlsoap.org/soap/envelope/', 't': 'http://tempuri.org/'}
            token_element = root.find('.//t:GetTokenResult', namespaces)
            if token_element is not None and token_element.text:
                CURRENT_TOKEN = token_element.text
                print(f"{VERDE}[+] Token nou obținut cu succes: {CURRENT_TOKEN[:15]}...{RESET}", flush=True)
                return CURRENT_TOKEN
        print(f"{ROSU}[!] Serverul a răspuns cu codul: {response.status_code}{RESET}", flush=True)
    except Exception as e:
        print(f"{ROSU}[!] Eroare la generarea token-ului: {e}{RESET}", flush=True)
    
    return None


def executa_cerere_search(an, pagina):
    """Trimite cererea XML de căutare pentru un anumit an și pagină."""
    global CURRENT_TOKEN
    
    if not CURRENT_TOKEN:
        obtine_token_nou()
        if not CURRENT_TOKEN:
            return None
        
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ILegislatieService/Search",
        "User-Agent": USER_AGENT
    }
    
    soap_request = f"""<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns0="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="http://schemas.microsoft.com/2003/10/Serialization/Arrays" xmlns:ns2="http://tempuri.org/">
       <SOAP-ENV:Header/>
       <ns0:Body>
          <ns2:Search>
             <ns2:SearchModel>
                <ns1:NumarPagina>{pagina}</ns1:NumarPagina>
                <ns1:RezultatePagina>100</ns1:RezultatePagina>
                <ns1:SearchAn>{an}</ns1:SearchAn>
             </ns2:SearchModel>
             <ns2:tokenKey>{CURRENT_TOKEN}</ns2:tokenKey>
          </ns2:Search>
       </ns0:Body>
    </SOAP-ENV:Envelope>"""

    try:
        response = requests.post(WSDL_URL, data=soap_request, headers=headers, timeout=15)
        return response
    except Exception as e:
        print(f"{ROSU}[!] Eroare conexiune la Search (An {an}, Pag {pagina}): {e}{RESET}", flush=True)
        return None


def ruleaza_scraping(an_start, an_end):
    global CURRENT_TOKEN
    
    for an in range(an_start, an_end + 1):
        pagina = 0
        while True:
            # --- LOGICA DE SKIP CU FORMATUL TĂU BRUT ORIGINAL ---
            nume_fisier = f"brut_legislatie_{an}_pag{pagina}.xml"
            
            if os.path.exists(nume_fisier):
                print(f"{GALBEN}[~] Pasăm peste: {nume_fisier} există deja.{RESET}", flush=True)
                pagina += 1
                continue
            
            print(f"[*] Se descarcă: Anul {an}, Pagina {pagina}...", flush=True)
            response = executa_cerere_search(an, pagina)
            
            if response is None:
                print(f"{ROSU}[!] Reîncercăm peste 10 secunde...{RESET}", flush=True)
                time.sleep(10)
                continue
                
            response_text = response.text
            
            # Auto-reparare token la expirare
            if "TOKEN INVALID" in response_text or "REGENERATI TOKEN" in response_text:
                print(f"{GALBEN}[!] Token expirat! Regenerăm...{RESET}", flush=True)
                obtine_token_nou()
                continue 
                
            if response.status_code != 200:
                print(f"{ROSU}[!] Eroare HTTP {response.status_code}. Reîncercăm...{RESET}", flush=True)
                time.sleep(5)
                continue

            # --- SALVARE CU NAMING-UL TĂU BRUT ---
            try:
                with open(nume_fisier, "w", encoding="utf-8") as f:
                    f.write(response_text)
                print(f"{VERDE}[+] Fișier salvat cu succes: {nume_fisier}{RESET}", flush=True)
            except Exception as e:
                print(f"{ROSU}[!] Eroare salvare {nume_fisier}: {e}{RESET}", flush=True)
            
            # Oprire pagină când nu mai sunt rezultate
            if "<a:TipAct>" not in response_text and "SearchResult" in response_text:
                print(f"[*] Gata cu paginile pe anul {an}.", flush=True)
                break
                
            pagina += 1
            time.sleep(1)


if __name__ == "__main__":
    ruleaza_scraping(2000, 2026)
