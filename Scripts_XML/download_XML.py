import sys
import os
import time
import json
import traceback
import requests
import http.client

# ==========================================
# CONFIGURĂRI ȘI CONSTANTE
# ==========================================
MAX_RETRIES_PER_PAGE = 4      # Încercări rapide per ciclu
MAX_FAILED_CYCLES = 3          # Câte cicluri mari de eșec permitem înainte să SĂRTIM pagina
PAUSE_BETWEEN_RETRIES = 3      # Pauza de start (secunde)
LOG_ERRORS_FILE = "pagini_saltate_erori.json"

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Connection': 'close'  # CRUCIAL: Oprește reutilizarea socket-urilor moarte / agățate
}


# ==========================================
# FUNCȚII AUXILIARE DE LOGARE ȘI DEBUG
# ==========================================
def logheaza_pagina_saltata(an, pagina, url, motiv_detaliat):
    """Salvează incremental paginile care au eșuat definitiv într-un fișier JSON."""
    entry = {
        "an": an,
        "pagina": pagina,
        "url": url,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "motiv": str(motiv_detaliat)
    }
    
    date_existente = []
    if os.path.exists(LOG_ERRORS_FILE):
        try:
            with open(LOG_ERRORS_FILE, "r", encoding="utf-8") as f:
                date_existente = json.load(f)
        except Exception:
            date_existente = []

    date_existente.append(entry)
    
    try:
        with open(LOG_ERRORS_FILE, "w", encoding="utf-8") as f:
            json.dump(date_existente, f, ensure_ascii=False, indent=2)
        print(f"   📝 [LOGGED] Pagina {pagina} din anul {an} a fost salvată în '{LOG_ERRORS_FILE}'.")
    except Exception as e:
        print(f"   ⚠️ Nu s-a putut scrie în fișierul de log: {e}")


def descarca_pagina_cu_debug(url, timeout=30):
    """
    Execută request-ul HTTP și afișează în clar orice cod de eroare
    sau excepție de rețea întâlnită (Status Code, Connection Drop, Timeout).
    """
    try:
        # Folosim session/request direct cu Connection: close
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        
        # 1. Răspuns Successful (200 OK)
        if response.status_code == 200:
            return True, response.content, "OK"
        
        # 2. Serverul a trimis un cod HTTP de eroare (404, 500, 502, 503, 504, 429 etc.)
        motiv = f"HTTP {response.status_code} ({response.reason})"
        print(f"\n   ⚠️ [HTTP STATUS ERROR] Cod {response.status_code} ({response.reason}) pe URL: {url}")
        if response.text:
            print(f"      📄 Preview Răspuns (200 chars): {response.text[:200]!r}")
        return False, None, motiv

    except requests.exceptions.HTTPError as e:
        motiv = f"HTTPError: {e}"
        print(f"\n   ❌ [HTTPError Exact]: {e}")
        return False, None, motiv
        
    except requests.exceptions.ConnectionError as e:
        # Prinde cazurile de RemoteDisconnected, ConnectionResetError, DNS failure etc.
        motiv = f"ConnectionError ({type(e).__name__}): {e}"
        print(f"\n   ❌ [ConnectionError Exact]: {type(e).__name__} -> {e}")
        return False, None, motiv

    except requests.exceptions.Timeout as e:
        motiv = f"Timeout ({timeout}s)"
        print(f"\n   ⏳ [Timeout Error]: Serverul nu a răspuns în {timeout} secunde.")
        return False, None, motiv

    except Exception as e:
        motiv = f"Eroare Necunoscută ({type(e).__name__}): {e}"
        print(f"\n   💥 [Eroare Generală]: {type(e).__name__} -> {e}")
        return False, None, motiv


# ==========================================
# BUCLA PRINCIPALĂ DE DESCĂRCARE PER AN/PAGINĂ
# ==========================================
def proceseaza_descarcare_an(an, pagina_start=1):
    """Procesează descărcarea paginilor pentru un an specific, cu tratare de erori și Skip."""
    print(f"\n=== AN INDUSTRIAL XML: {an} ===")
    print(f"🆕 An {an}: Începem de la pagina {pagina_start}.")
    
    pagina_curenta = pagina_start
    cicluri_esuate_consecutive = 0
    
    # Adaptează URL-ul la structura ta exactă de endpoint:
    # URL_BASE = f"https://.../?an={an}&pagina="
    
    while True:
        url_pagina = f"https://legislatie.just.ro/..." # <-- Inserare URL exact
        print(f"--- [AVANS] An {an} / Pagina {pagina_curenta} ---")
        
        succes = False
        ultimul_motiv_esec = ""
        
        # Cele 4 încercări rapide
        for incercare in range(1, MAX_RETRIES_PER_PAGE + 1):
            pauza = PAUSE_BETWEEN_RETRIES * (2 ** (incercare - 1)) # Backoff: 3s, 6s, 12s, 24s
            
            ok, continut, motiv = descarca_pagina_cu_debug(url_pagina)
            
            if ok:
                succes = True
                cicluri_esuate_consecutive = 0  # Resetăm contorul de erori la succes
                
                # --- AICI SUNT PROCESATE ȘI SALVATE DATELE XML ---
                # salveaza_xml_pe_drive_sau_disc(an, pagina_curenta, continut)
                # ------------------------------------------------
                
                break  # Ieșim din bucla de retry
            else:
                ultimul_motiv_esec = motiv
                print(f"   ⚠️ Attempt {incercare}/{MAX_RETRIES_PER_PAGE} eșuat pe pagina {pagina_curenta}. Pauză {pauza}s...")
                time.sleep(pauza)
        
        if succes:
            pagina_curenta += 1
            # Aici poți adăuga condiția de oprire pentru anul respectiv dacă se cunoaște numărul maxim de pagini
        else:
            cicluri_esuate_consecutive += 1
            print(f"\n🛑 [Pagină Eșuată] Pagina {pagina_curenta} a eșuat complet în ciclul curent ({cicluri_esuate_consecutive}/{MAX_FAILED_CYCLES}).")
            
            # DACA A EȘUAT DE PREA MULTE ORI CONSECUTIV -> SALT DE PAGINĂ (SKIP)
            if cicluri_esuate_consecutive >= MAX_FAILED_CYCLES:
                print(f"⚠️ [SKIP PAGINĂ] Pagina {pagina_curenta} eșuează sistematic! O salvăm în log și SĂRTIM la pagina {pagina_curenta + 1}...")
                
                logheaza_pagina_saltata(
                    an=an, 
                    pagina=pagina_curenta, 
                    url=url_pagina, 
                    motiv_detaliat=ultimul_motiv_esec
                )
                
                # Deblocăm bucla prin avansare directă!
                pagina_curenta += 1
                cicluri_esuate_consecutive = 0
            else:
                print("   ⏸️ Așteptăm 30 de secunde înainte de a reîncerca aceeași pagină...")
                time.sleep(30)


# ==========================================
# MAIN ENTRYPOINT (WRAPPER GLOBAL ANTI-CRASH)
# ==========================================
def main():
    print("🚀 Script de descărcare XML pornit.")
    
    # Preluare argumente din linia de comandă (ex: python download_XML.py 2012 2013)
    ani_de_procesat = [2012, 2013]
    if len(sys.argv) >= 3:
        try:
            an_start = int(sys.argv[1])
            an_stop = int(sys.argv[2])
            ani_de_procesat = list(range(an_start, an_stop + 1))
        except ValueError:
            print("⚠️ Argumentele din linia de comandă nu sunt numere valide. Folosim valorile default.")

    for an in ani_de_procesat:
        proceseaza_descarcare_an(an, pagina_start=2480 if an == 2012 else 1)

    print("\n✅ Descărcare încheiată cu succes pentru toți anii specificați!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Procestul a fost întrerupt manual de utilizator (Ctrl+C). Exiting cleanly...")
        sys.exit(0)
    except Exception as e:
        # PRINDERE GLOBALĂ A ERORILOR: Oprește prăbușirea prin `/usr/bin/bash -e`
        print(f"\n💥 [CRITICAL SCRIPT ERROR] A apărut o eroare fatală neprinsă:")
        print(f"   Tip Eroare: {type(e).__name__}")
        print(f"   Mesaj: {e}")
        print("\n📜 Traceback complet:")
        traceback.print_exc()
        
        print("\n🛡️ Prevenim părăsirea scriptului cu exit-code diferit de zero pentru a păstra log-urile intacte.")
        # Salvează orice stare temporară dacă este necesar
        sys.exit(0)
