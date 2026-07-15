import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from zeep import Client, Settings
from zeep.exceptions import Fault

# Activăm logarea pentru detalii suplimentare
logging.basicConfig(level=logging.INFO)
logging.getLogger('zeep.transports').setLevel(logging.WARNING) # Am redus din logurile XML să fie consola curată

# Configurații API Just.ro
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

# Configurare Zeep pentru a tolera schemele XML complexe
settings = Settings(strict=False, xml_huge_tree=True)
client = Client(wsdl=WSDL_URL, settings=settings)

# Definim strict doar parametrii acceptați de CompositeType în WSDL-ul Just.ro
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
    """Obține un token proaspăt de sesiune de la API-ul Just.ro."""
    try:
        safe_print("[🔑] Inițializare: Obținem token nou pentru Portalul Legislativ...")
        token = client.service.GetToken()
        safe_print(f"[🔑] Token generat cu succes: {token[:15]}...")
        return token
    except Exception as e:
        safe_print(f"❌ Eroare critică la obținerea token-ului: {e}")
        return None

def curata_si_formateaza_parametri(parametri_raw):
    """
    Filtrează dicționarul de parametri pentru a păstra doar cheile permise.
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
    """Trimite cererea de căutare corectată structural către API."""
    
    # Parametrii tăi originali
    parametri_raw = {
        'NumarPagina': pagina,
        'RezultatePagina': rezultate_per_pagina,
        'SearchAn': an,
        'SearchDomeniu': None,
        'SearchEmitent': None,
        'SearchModificata': None,
        'SearchNumar': None,
        'SearchRepublicata': None, # Aceasta era prima eroare (eliminată prin filtrare)
        'SearchText': None,
        'SearchTip': None,
        'SearchTitlu': None
    }
    
    # Curățăm parametrii pentru CompositeType
    parametri_filtrati = curata_si_formateaza_parametri(parametri_raw)
    
    safe_print(f"🔍 [An {an}][Pagina {pagina}] Trimitem cerere către API...")
    
    try:
        # CORECTURĂ: Am schimbat din SearchParam/token în SearchModel/tokenKey
        rezultat = client.service.Search(
            SearchModel=parametri_filtrati,
            tokenKey=token
        )
        
        safe_print(f"✅ [An {an}][Pagina {pagina}] Succes! Am primit rezultatele.")
        return rezultat
        
    except Fault as soap_fault:
        safe_print(f"⚠️ [An {an}] Eroare SOAP: {soap_fault}")
    except Exception as e:
        safe_print(f"⚠️ [An {an}] Excepție neașteptată: {e}")
    
    return None

def porneste_crawler():
    """Funcția principală care orchestrează thread-urile."""
    token = obtine_token_nou()
    if not token:
        safe_print("🛑 Imposibil de continuat fără token valid.")
        return
        
    ani_de_procesat = list(range(2000, 2020)) # Interval ani: 2000 - 2019
    max_threads = 4
    
    safe_print(f"📅 Interval ani selectat: 2000 - 2019")
    safe_print(f"🧵 Thread-uri active: {max_threads}")
    
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(crawleaza_an_si_pagina, token, an, 0) for an in ani_de_procesat]
        for future in futures:
            future.result()

if __name__ == "__main__":
    porneste_crawler()
