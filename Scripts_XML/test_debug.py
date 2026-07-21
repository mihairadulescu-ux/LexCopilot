import sys
import traceback
import requests

# URL-ul pe care vrei să îl testezi (înlocuiește cu endpoint-ul exact SOAP / API sau pagina HTML)
URL_TEST = "https://legislatie.just.ro/"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ro-RO,ro;q=0.9,en-US;q=0.8',
    'Connection': 'close'
}

def testeaza_conversatia():
    print(f"🔍 [TEST] Inițiem cererea către: {URL_TEST}\n")
    
    try:
        # Activați stream=True pentru a putea inspecta socket-ul și headerele înainte de a descărca corpul
        response = requests.get(
            URL_TEST, 
            headers=HEADERS, 
            timeout=15, 
            verify=True
        )
        
        print("=== STATUS RĂSPUNS ===")
        print(f"Cod Stare HTTP : {response.status_code} {response.reason}")
        print(f"Versiune HTTP  : {getattr(response.raw, 'version', 'N/A')}")
        
        print("\n=== HEADERE PRIMITE DE LA SERVER ===")
        for key, value in response.headers.items():
            print(f"{key}: {value}")
            
        print("\n=== PREVIEW CONȚINUT (primele 500 caractere) ===")
        print(response.text[:500])
        
    except requests.exceptions.SSLError as e:
        print("\n❌ [EROARE SSL/TLS]: Problema este la negocierea certificatului sau a versiunii TLS.")
        print(f"Detaliu: {e}")
        
    except requests.exceptions.ConnectionError as e:
        print("\n❌ [EROARE CONEXIUNE / SOCKET]: Serverul a închis brutal conexiunea (TCP Reset / Remote Disconnect).")
        print(f"Detaliu: {e}")
        
    except requests.exceptions.Timeout as e:
        print("\n⏳ [TIMEOUT]: Serverul nu a răspuns în timpul alocat.")
        
    except Exception as e:
        print(f"\n💥 [EXCEPȚIE NEAȘTEPTATĂ]: {type(e).__name__} -> {e}")
        traceback.print_exc()

if __name__ == "__main__":
    testeaza_conversatia()
