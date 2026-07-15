import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from zeep import Client, Settings
from zeep.exceptions import Fault
from zeep.plugins import HistoryPlugin  # Necesar pentru a prinde XML-ul brut
from lxml import etree                  # Pentru a procesa și formata frumos XML-ul

# Reducem logurile la minim
logging.basicConfig(level=logging.INFO)
logging.getLogger('zeep.transports').setLevel(logging.WARNING)

# URL-ul oficial pentru Portalul Legislativ Just.ro
WSDL_URL = "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl"

# Folderul unde se vor salva XML-urile
FOLDER_DESCARCARE = "legi_xml_brut"
os.makedirs(FOLDER_DESCARCARE, exist_ok=True)

# Singurele 6 chei permise de structura "CompositeType" a API-ului
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

def curata_si_formateaza_parametri(parametri_raw):
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

def salveaza_xml_fizic(an, pagina, xml_element):
    """Transformă elementul XML primit într-un string formatat și îl scrie pe disk."""
    # Convertim elementul XML în bytes (cu indentare frumoasă)
    xml_brut_bytes = etree.tostring(xml_element, pretty_print=True, encoding='utf-8')
    
    # Numele fișierului brut (ex: legi_xml_brut/an_2000_pag_0.xml)
    nume_fisier = os.path.join(FOLDER_DESCARCARE, f"an_{an}_pag_{pagina}.xml")
    
    with open(nume_fisier, "wb") as f:
        f.write(xml_brut_bytes)
        
    safe_print(f"💾 [An {an}][Pagina {pagina}] XML brut salvat în: {nume_fisier}")

def crawleaza_an_complet(an, rezultate_per_pagina=50):
    """
    Descarcă TOATE paginile sub formă de XML brut pentru un an anume.
    Fiecare fir de execuție își creează propriul client cu propriul istoric (Thread-Safe).
    """
    # Creăm un istoric și un client Zeep dedicat pentru acest thread
    history = HistoryPlugin()
    settings = Settings(strict=False, xml_huge_tree=True)
    client = Client(wsdl=WSDL_URL, settings=settings, plugins=[history])
    
    # Obținem token-ul în interiorul thread-ului
    try:
        token = client.service.GetToken()
    except Exception as e:
        safe_print(f"🛑 [An {an}] Nu s-a putut obține token-ul: {e}")
        return

    pagina = 0
    
    while True:
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
        
        parametri_filtrati = curata_si_formateaza_parametri(parametri_raw)
        safe_print(f"🔍 [An {an}][Pagina {pagina}] Se descarcă XML-ul...")
        
        try:
            # Apelăm serverul Just.ro
            rezultat = client.service.Search(
                SearchModel=parametri_filtrati,
                tokenKey=token
            )
            
            # Verificăm dacă răspunsul conține date valide
            # (dacă rezultatul e complet gol sau nu conține legi, ne oprim)
            if not rezultat or not hasattr(rezultat, 'Legi') or not rezultat.Legi or len(rezultat.Legi._value_1) == 0:
                safe_print(f"🛑 [An {an}] Nu mai există pagini. Ne oprim la pagina {pagina}.")
                break
                
            # Dacă avem date, extragem XML-ul brut primit prin rețea de la pluginul de istoric
            xml_primit = history.last_received
            
            if xml_primit is not None:
                salveaza_xml_fizic(an, pagina, xml_primit)
            else:
                safe_print(f"⚠️ [An {an}][Pagina {pagina}] Nu s-a putut captura XML-ul din istoric.")
            
            pagina += 1
            
        except Fault as soap_fault:
            safe_print(f"⚠️ [An {an}] Eroare SOAP la pagina {pagina}: {soap_fault}")
            break
        except Exception as e:
            safe_print(f"⚠️ [An {an}] Excepție la pagina {pagina}: {e}")
            break

def porneste_crawler():
    """Pornește descărcarea legislativă pe 4 fire de execuție în paralel."""
    ani_de_procesat = list(range(2000, 2020))  # Intervalul tău: 2000 - 2019
    max_threads = 4
    
    safe_print(f"📅 Interval ani: 2000 - 2019")
    safe_print(f"🧵 Se pornesc cele {max_threads} thread-uri active...")
    
    # Împărțim munca în mod egal pe thread-uri
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        # Trimitem doar anul ca parametru; fiecare thread își va genera singur token-ul lui și clientul lui SOAP securizat
        executor.map(crawleaza_an_complet, ani_de_procesat)

if __name__ == "__main__":
    porneste_crawler()
