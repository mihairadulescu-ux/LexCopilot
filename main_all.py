import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from zeep import Client, Settings
from zeep.exceptions import Fault

# Activăm logarea pentru a vedea detaliile SOAP în consolă (la fel ca în logurile tale)
logging.basicConfig(level=logging.INFO)
logging.getLogger('zeep.transports').setLevel(logging.DEBUG)

# Configurații API Just.ro
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

# Configurare Zeep pentru a fi mai tolerant cu schemele XML
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

# Blocaj pentru a asigura scrierea ordonată în consolă din thread-uri diferite
print_lock = threading.Lock()

def safe_print(message):
    with print_lock:
        print(message)

def obtine_token_nou():
    """Obține un token proaspăt de sesiune de la API-ul Just.ro."""
    try:
        safe_print("[🔑] Inițializare: Obținem token nou pentru Portalul Legislativ...")
        # Apelăm metoda GetToken expusă de serviciul SOAP
        token = client.service.GetToken()
        safe_print(f"[🔑] Token generat cu succes: {token[:15]}...")
        return token
    except Exception as e:
        safe_print(f"❌ Eroare critică la obținerea token-ului: {e}")
        return None

def curata_si_formateaza_parametri(parametri_raw):
    """
    Filtrează dicționarul de parametri pentru a păstra doar cheile permise 
    și formatează corect tipurile de date conform WSDL-ului (int și string).
    """
    parametri_curati = {}
    
    for cheie in CHIEI_PERMISE_SOAP:
        valoare = parametri_raw.get(cheie, None)
        
        # Tratăm parametrii numerici (trebuie să fie int)
        if cheie in ['NumarPagina', 'RezultatePagina']:
            parametri_curati[cheie] = int(valoare) if valoare is not None else 0
        else:
            # Tratăm parametrii de tip text (trebuie să fie string, nu None)
            if valoare is None:
                parametri_curati[cheie] = ""
            else:
                parametri_curati[cheie] = str(valoare)
                
    return parametri_curati

def crawleaza_an_si_pagina(token, an, pagina=0, rezultate_per_pagina=50):
    """Trimite cererea de căutare curățată către API."""
    
    # Aceștia sunt parametrii compleți pe care probabil îi avea crawlerul tău inițial
    parametri_raw = {
        'NumarPagina': pagina,
        'RezultatePagina': rezultate_per_pagina,
        'SearchAn': an,
        'SearchDomeniu': None,      # Va fi eliminat la filtrare
        'SearchEmitent': None,      # Va fi eliminat la filtrare
        'SearchModificata': None,   # Va fi eliminat la filtrare
        'SearchNumar': None,
        'SearchRepublicata': None,  # Va fi eliminat la filtrare (Cauza erorii!)
        'SearchText': None,
        'SearchTip': None,          # Va fi eliminat la filtrare
        'SearchTitlu': None
    }
    
    # Aplicăm curățarea automată
    parametri_filtrati = curata_si_formateaza_parametri(parametri_raw)
    
    safe_print(f"🔍 [An {an}][Pagina {pagina}] Trimitem cerere cu parametrii filtrați: {parametri_filtrati}")
    
    try:
        # Recreăm structura exactă pe care o cere serviciul SOAP Just.ro.
        # În funcție de numele exact al metodei din WSDL, acesta se apelează de regulă ca mai jos.
        # Parametrul 'SearchParam' este obiectul de tip CompositeType.
        rezultat = client.service.Search(
            token=token,
            SearchParam=parametri_filtrati
        )
        
        safe_print(f"✅ [An {an}][Pagina {pagina}] Succes! Am primit rezultatele.")
        return rezultat
        
    except Fault as soap_fault:
        safe_print(f"⚠️ [An {an}] Eroare de protocol SOAP la pagina {pagina}: {soap_fault}")
    except Exception as e:
        safe_print(f"⚠️ [An {an}] Excepție neașteptată la pagina {pagina}: {e}")
    
    return None

def porneste_crawler():
    """Funcția principală care orchestrează thread-urile și intervalul de ani."""
    token = obtine_token_nou()
    if not token:
        safe_print("🛑 Imposibil de continuat fără token valid.")
        return
        
    ani_de_procesat = list(range(2000, 2020)) # Interval ani: 2000 - 2019
    max_threads = 4
    
    safe_print(f"📅 Interval ani selectat: 2000 - 2019")
    safe_print(f"🧵 Thread-uri active: {max_threads}")
    
    # Folosim un ThreadPoolExecutor pentru a gestiona cele 4 thread-uri simultan
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        # Trimitem joburile în paralel pentru fiecare an în parte (începând cu pagina 0)
        futures = [executor.submit(crawleaza_an_si_pagina, token, an, 0) for an in ani_de_procesat]
        
        # Așteptăm ca toate thread-urile să își termine execuția curentă
        for future in futures:
            future.result()

if __name__ == "__main__":
    porneste_crawler()
