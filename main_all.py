mport os
import time
import requests
import xml.etree.ElementTree as ET

# --- CODURI CULORI ANSI PENTRU CONSOLĂ ---
VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

# --- CONFIGURARE CREDENȚIALE ȘI URL-URI ---
WSDL_URL = "http://legislatie.just.ro/api/LegislatieService.svc"
USER_NAME = "utilizatorul_tau"
PASSWORD = "parola_ta"

CURRENT_TOKEN = None

def obtine_token_nou():
    """Apelează serviciul de autentificare pentru a genera un token proaspăt."""
    global CURRENT_TOKEN
    print(f"{GALBEN}[-] Se solicită un token nou de la server...{RESET}")
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ILegislatieService/Login"
    }
    
    soap_request = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tem="http://tempuri.org/">
       <soapenv:Header/>
       <soapenv:Body>
          <tem:Login>
             <tem:username>{USER_NAME}</tem:username>
             <tem:password>{PASSWORD}</tem:password>
          </tem:Login>
       </soapenv:Body>
    </soapenv:Envelope>"""
    
    try:
        response = requests.post(WSDL_URL, data=soap_request, headers=headers, timeout=30)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            namespaces = {'s': 'http://schemas.xmlsoap.org/soap/envelope/', 't': 'http://tempuri.org/'}
            token_element = root.find('.//t:LoginResult', namespaces)
            if token_element is not None and token_element.text:
                CURRENT_TOKEN = token_element.text
                print(f"{VERDE}[+] Token nou obținut cu succes: {CURRENT_TOKEN[:15]}...{RESET}")
                return CURRENT_TOKEN
        print(f"{ROSU}[!] Eroare la obținerea token-ului. Cod status: {response.status_code}{RESET}")
    except Exception as e:
        print(f"{ROSU}[!] Excepție la generarea token-ului: {e}{RESET}")
    
    return None


def executa_cerere_search(an, pagina):
    """Trimite cererea XML de căutare pentru un anumit an și pagină."""
    global CURRENT_TOKEN
    
    if not CURRENT_TOKEN:
        obtine_token_nou()
        
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
        response = requests.post(WSDL_URL, data=soap_request, headers=headers, timeout=30)
        return response
    except Exception as e:
        print(f"{ROSU}[!] Eroare de conexiune la cerere: {e}{RESET}")
        return None


def ruleaza_scraping(an_start, an_end):
    global CURRENT_TOKEN
    
    for an in range(an_start, an_end + 1):
        pagina = 0
        while True:
            print(f"[*] Se descarcă: Anul {an}, Pagina {pagina}...")
            response = executa_cerere_search(an, pagina)
            
            if response is None:
                print(f"{ROSU}[!] Server inaccesibil. Reîncercăm în 10 secunde...{RESET}")
                time.sleep(10)
                continue
                
            response_text = response.text
            
            # Verificare expirare token
            if "TOKEN INVALID" in response_text or "REGENERATI TOKEN" in response_text:
                print(f"{GALBEN}[!] Token expirat detectat! Pornim procedura de re-autentificare...{RESET}")
                obtine_token_nou()
                continue 
                
            if response.status_code != 200:
                print(f"{ROSU}[!] Eroare HTTP {response.status_code}. Reîncercăm în 5 secunde...{RESET}")
                time.sleep(5)
                continue

            # --- SALVARE CU NAMING BRUT ORIGINAL ---
            nume_fisier = f"response_raw_{an}_pag_{pagina}.xml"
            
            try:
                with open(nume_fisier, "w", encoding="utf-8") as f:
                    f.write(response_text)
                # Mesajul de succes este acum complet verde
                print(f"{VERDE}[+] Fișier salvat cu succes: {nume_fisier}{RESET}")
            except Exception as e:
                print(f"{ROSU}[!] Eroare la scrierea fișierului {nume_fisier}: {e}{RESET}")
            
            # Condiție oprire paginare pe anul curent
            if "<a:TipAct>" not in response_text and "SearchResult" in response_text:
                print(f"[*] Am terminat toate paginile pentru anul {an}.")
                break
                
            pagina += 1
            time.sleep(1)


if __name__ == "__main__":
   
    
    ruleaza_scraping(2000, 2026)
