import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from zeep import Client, Settings
from zeep.exceptions import Fault

# Oprim logurile de debugging ca să nu îți umple consola de XML-uri greu de citit
logging.basicConfig(level=logging.INFO)
logging.getLogger('zeep.transports').setLevel(logging.WARNING)

# Link-ul oficial al API-ului Just.ro
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

# Setați Zeep să fie tolerant cu micile imperfecțiuni din schema XML a lor
settings = Settings(strict=False, xml_huge_tree=True)
client = Client(wsdl=WSDL_URL, settings=settings)

# Acestea sunt singurele chei pe care structura "CompositeType" a Just.ro le acceptă
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
    """Obține cheia de sesiune necesară pentru căutare."""
    try:
        safe_print("[🔑] Inițializare: Obținem token nou pentru Portalul Legislativ...")
        token = client.service.GetToken()
        safe_print(f"[🔑] Token generat cu succes: {token[:15]}...")
        return token
    except Exception as e:
        safe_print(f"❌ Eroare critică la obținerea token-ului: {e}")
        return None

def curata_si_formateaza_parametri(parametri_raw):
    """Filtrează parametrii și elimină cheile invalide precum SearchRepublicata sau SearchTip."""
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
    """Trimite cererea formatată corect către server."""
    
    # Parametrii tăi inițiali (cu tot cu cei problematici pe care îi curățăm imediat)
    parametri_raw = {
        'NumarPagina': pagina,
        'RezultatePagina': rezultate_per_pagina,
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
    
    # Păstrăm doar cele 6 chei permise
    parametri_filtrati = curata_si_formateaza_parametri(parametri_raw)
    
    safe_print(f"🔍 [An {an}][Pagina {pagina}] Se trimite cererea...")
    
    try:
        # CORECTURĂ: Folosim exact 'SearchModel' și 'tokenKey' cerute de serverul lor
        rezultat = client.service.Search(
            SearchModel=parametri_filtrati,
            tokenKey=token
        )
        
        safe_print(f"✅ [An {an}][Pagina {pagina}] Succes! Am primit rezultatele.")
        return rezultat
        
    except Fault as soap_fault:
        safe_print(f"⚠️ [An {an}] Eroare SOAP la pagina {pagina}: {soap_fault}")
    except Exception as e:
        safe_print(f"⚠️ [An {an}] Excepție neașteptată la pagina {pagina}: {e}")
    
    return None

def porneste_crawler():
    """Pornește descărcarea pe cele 4 fire de execuție în paralel."""
    token = obtine_token_nou()
    if not token:
        safe_print("🛑 Imposibil de continuat fără token valid.")
        return
        
    ani_de_procesat = list(range(2000, 2020)) # Ani de la 2000 la 2019
    max_threads = 4
    
    safe_print(f"📅 Interval ani selectat: 2000 - 2019")
    safe_print(f"🧵 Se pornesc cele {max_threads} thread-uri active...")
    
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(crawleaza_an_si_pagina, token, an, 0) for an in ani_de_procesat]
        for future in futures:
            future.result()

if __name__ == "__main__":
    porneste_crawler()
