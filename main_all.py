import os
import time
import requests
import xml.etree.ElementTree as ET

# --- CODURI CULORI ANSI PENTRU CONSOLĂ (se văd verzi pe GitHub) ---
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

# --- URL REAL JUST.RO ---
WSDL_URL = "http://legislatie.just.ro/api/legis/LegislatieService.svc"

CURRENT_TOKEN = None

def obtine_token_nou():
    """Apelează serviciul public pentru a genera un token nou."""
    global CURRENT_TOKEN
    # flush=True obligă GitHub să afișeze instant acest mesaj!
    print(f"{GALBEN}[-] Se încearcă conectarea la Just.ro pentru un token nou...{RESET}", flush=True)
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ILegislatieService/GetToken"
    }
    
    soap_request = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tem="http://tempuri.org/">
       <soapenv:Header/>
       <soapenv:Body>
          <tem:GetToken/>
       </soapenv:Body>
    </soapenv:Envelope>"""
    
    try:
        # Am scăzut timeout la 10 secunde ca să nu stea blocat infinit dacă GitHub e blocat de Just.ro
        response = requests.post(WSDL_URL, data=soap_request, headers=headers, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            namespaces = {'s': 'http://schemas.xmlsoap.org/soap/envelope/', 't': 'http://tempuri.org/'}
            token_element = root.find('.//t:GetTokenResult', namespaces)
            if token_element is not None and token_element.text:
                CURRENT_TOKEN = token_element.text
                print(f"{VERDE}[+] Token nou obținut cu succes: {CURRENT_TOKEN[:15]}...{RESET}", flush=True)
                return CURRENT_TOKEN
        print(f"{ROSU}[!] Serverul a răspuns cu codul: {response.status_code}{RESET}", flush=True)
    except requests.exceptions.Timeout:
        print(f"{ROSU}[!] TIMEOUT: Serverul Just.ro nu a răspuns în 10 secunde. Probabil IP-ul de GitHub este blocat!{RESET}", flush=True)
    except Exception as e:
        print(f"{ROSU}[!] Eroare la generarea token-ului: {e}{RESET}", flush=True)
    
    return None


def executa_cerere_search(an, pagina):
    """Trimite cererea XML de căutare pentru un anumit an și pagină."""
    global CURRENT_TOKEN
    
    if not CURRENT_TOKEN:
        obtine_token_nou()
        if not CURRENT_TOKEN:
            return None # Dacă tot nu avem token, nu mai facem cererea
        
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ILegislatieService/Search"
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
        response = requests.post(WSDL_URL, data=soap_request, headers=headers, timeout=10)
        return response
    except Exception as e:
        print(f"{ROSU}[!] Eroare conexiune la Search (An {an}, Pag {pagina}): {e}{RESET}", flush=True)
        return None


def ruleaza_scraping(an_start, an_end):
    global CURRENT_TOKEN
    
    for an in range(an_start, an_end + 1):
        pagina = 0
        while True:
            nume_fisier = f"response_raw_{an}_pag_{pagina}.xml"
            
            # --- LOGICA DE SKIP ---
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
            
            if "TOKEN INVALID" in response_text or "REGENERATI TOKEN" in response_text:
                print(f"{GALBEN}[!] Token expirat! Regenerăm...{RESET}", flush=True)
                obtine_token_nou()
                continue 
                
            if response.status_code != 200:
                print(f"{ROSU}[!] Eroare HTTP {response.status_code}. Reîncercăm...{RESET}", flush=True)
                time.sleep(5)
                continue

            # --- SALVARE ---
            try:
                with open(nume_fisier, "w", encoding="utf-8") as f:
                    f.write(response_text)
                print(f"{VERDE}[+] Fișier salvat cu succes: {nume_fisier}{RESET}", flush=True)
            except Exception as e:
                print(f"{ROSU}[!] Eroare salvare {nume_fisier}: {e}{RESET}", flush=True)
            
            if "<a:TipAct>" not in response_text and "SearchResult" in response_text:
                print(f"[*] Gata cu paginile pe anul {an}.", flush=True)
                break
                
            pagina += 1
            time.sleep(1)


if __name__ == "__main__":
    ruleaza_scraping(2000, 2026)
