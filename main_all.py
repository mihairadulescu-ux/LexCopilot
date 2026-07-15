import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from zeep import Client, Settings
from zeep.exceptions import Fault

# Reducem logurile la minim ca să ruleze rapid și curat în consolă
logging.basicConfig(level=logging.INFO)
logging.getLogger('zeep.transports').setLevel(logging.WARNING)

# URL-ul oficial pentru Portalul Legislativ Just.ro
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

# Setați Zeep să ignore micile probleme de validare din XML-ul lor oficial
settings = Settings(strict=False, xml_huge_tree=True)
client = Client(wsdl=WSDL_URL, settings=settings)

# Acestea sunt singurele 6 chei pe care structura lor de date ("CompositeType") le acceptă în mod real
CHIEI_PERMISE_SOAP = {
    'NumarPagina',
    'RezultatePagina',
    'SearchAn',
    'SearchNumar',
    'SearchText',
    'SearchTitlu'
}

print_lock = threading.Lock()

def safe_print(message):
    with print_lock:
        print(message)

def obtine_token_nou():
    """Obține cheia de sesiune pentru căutare."""
    try:
        safe_print("[🔑] Inițializare: Obținem token nou...")
        token = client.service.GetToken()
        safe_print(f"[🔑] Token primit: {token[:15]}...")
        return token
    except Exception as e:
        safe_print(f"❌ Eroare critică la generare token: {e}")
        return None

def curata_si_formateaza_parametri(parametri_raw):
    """
    Filtrează dicționarul de parametri pentru a păstra doar cheile permise 
    și rezolvă problema cu 'SearchRepublicata', 'SearchTip' etc.
    """
    parametri_curati = {}
    for cheie in CHIEI_PERMISE_SOAP:
        valoare = parametri_raw.get(cheie, None)
        
        if cheie in ['NumarPagina', 'RezultatePagina']:
            parametri_curati[cheie] = int(valoare) if valoare is not None else 0
        else:
            if valoare is None:
                parametri_curati[cheie] = ""
            else:
                parametri_curati[cheie] = str(valoare)
                
    return parametri_curati

def crawleaza_an_si_pagina(token, an, pagina=0, rezultate_per_pagina=50):
    """Trimite cererea formatată exact după specificațiile Just.ro."""
    
    # Lista de parametri pe care probabil o folosea scriptul tău inițial
    parametri_raw = {
        'NumarPagina': pagina,
        'RezultatePagina': rezultate_per_pagina,
        'SearchAn': an,
        'SearchDomeniu': None,
        'SearchEmitent': None,
        'SearchModificata': None,
        'SearchNumar': None,
        'SearchRepublicata': None, # Cauza inițială a blocajului (eliminată prin curățare)
        'SearchText': None,
        'SearchTip': None,
        'SearchTitlu': None
    }
    
    # Păstrăm doar cele 6 chei permise din CHIEI_PERMISE_SOAP
    parametri_filtrati = curata_si_formateaza_parametri(parametri_raw)
    
    safe_print(f"🔍 [An {an}][Pagina {pagina}] Se efectuează căutarea...")
    
    try:
        # CORECTURĂ STRUCTURALĂ: Trimitem exact 'SearchModel' și 'tokenKey'
        rezultat = client.service.Search(
            SearchModel=parametri_filtrati,
            tokenKey=token
        )
        
        # Procesăm datele dacă am primit un răspuns valid
        if rezultat:
            # În funcție de cum aveai structurat codul de salvare a rezultatelor, 
            # aici le poți manipula (ex: salvare în fișiere, baze de date etc.)
            safe_print(f"✅ [An {an}][Pagina {pagina}] Succes! Am primit datele.")
        else:
            safe_print(f"ℹ️ [An {an}][Pagina {pagina}] Nu s-au găsit rezultate.")
            
        return rezultat
        
    except Fault as soap_fault:
        safe_print(f"⚠️ [An {an}] Eroare SOAP la pagina {pagina}: {soap_fault}")
    except Exception as e:
        safe_print(f"⚠️ [An {an}] Excepție neașteptată la pagina {pagina}: {e}")
    
    return None

def porneste_crawler():
    """Pornește descărcarea legislativă pe 4 fire de execuție în paralel."""
    token = obtine_token_nou()
    if not token:
        safe_print("🛑 Imposibil de continuat fără token valid.")
        return
        
    ani_de_procesat = list(range(2000, 2020)) # Va procesa anii: 2000 - 2019
    max_threads = 4
    
    safe_print(f"📅 Interval ani: 2000 - 2019")
    safe_print(f"🧵 Thread-uri active: {max_threads}")
    
    # ThreadPoolExecutor se ocupă de rularea pe cele 4 fire de execuție
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(crawleaza_an_si_pagina, token, an, 0) for an in ani_de_procesat]
        for future in futures:
            future.result()

if __name__ == "__main__":
    porneste_crawler()
