import sys
import os
import time
import json
import traceback
import subprocess

# Auto-instalare dinamică pentru curl_cffi dacă nu este găsit în mediu
try:
    from curl_cffi import requests
except ImportError:
    print("📦 Pachetul 'curl_cffi' nu a fost găsit. Se instalează automat...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "curl_cffi"])
    from curl_cffi import requests
    print("✅ 'curl_cffi' a fost instalat cu succes!", flush=True)


# ==========================================
# CONFIGURĂRI ȘI CONSTANTE
# ==========================================
MAX_RETRIES_PER_PAGE = 4      # Încercări rapide per ciclu (3s, 6s, 12s, 24s)
MAX_FAILED_CYCLES = 3          # Câte cicluri de eșec permitem înainte să SĂRTIM pagina
PAUSE_BETWEEN_RETRIES = 3      # Pauza de start (secunde)
LOG_ERRORS_FILE = "pagini_saltate_erori.json"

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7',
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
        print(f"   📝 [LOGGED] Pagina {pagina} din anul {an} a fost salvată în '{LOG_ERRORS_FILE}'.", flush=True)
    except Exception as e:
        print(f"   ⚠️ Nu s-a putut scrie în fișierul de log: {e}", flush=True)


def descarca_pagina_cu_debug(url, timeout=30):
    """
    Execută request-ul HTTP folosind curl_cffi cu impresie de Chrome 120
    pentru a evita blocajele la nivel de TLS fingerprinting.
    """
    try:
        response = requests.get(
            url, 
            headers=DEFAULT_HEADERS, 
            impersonate="chrome120", 
            timeout=timeout
        )
        
        # 1. Răspuns Successful (200 OK)
        if response.status_code == 200:
            return True, response.content, "OK"
        
        # 2. Cod HTTP de eroare (404, 500, 502, 503, 504, 429 etc.)
        motiv = f"HTTP {response.status_code} ({response.reason})"
        print(f"\n   ⚠️ [HTTP STATUS ERROR] Cod {response.status_code} ({response.reason}) pe URL: {url}", flush=True)
        if response.text:
            print(f"      📄 Preview Răspuns (200 chars): {response.text[:200]!r}", flush=True)
        return False, None, motiv

    except requests.errors.RequestsError as e:
        motiv = f"curl_cffi Error ({type(e).__name__}): {e}"
        print(f"\n   ❌ [cURL Error Exact]: {type(e).__name__} -> {e}", flush=True)
        return False, None, motiv

    except Exception as e:
        motiv = f"Eroare Necunoscută ({type(e).__name__}): {e}"
        print(f"\n   💥 [Eroare Generală]: {type(e).__name__} -> {e}", flush=True)
        return False, None, motiv


# ==========================================
# BUCLA PRINCIPALĂ DE DESCĂRCARE PER AN/PAGINĂ
# ==========================================
def proceseaza_descarcare_an(an, pagina_start=1):
    """Procesează descărcarea paginilor pentru un an specific, cu tratare de erori și Skip."""
    print(f"\n=== AN INDUSTRIAL XML: {an} ===", flush=True)
    print(f"🆕 An {an}: Începem de la pagina {pagina_start}.", flush=True)
    
    pagina_curenta = pagina_start
    cicluri_esuate_consecutive = 0
    
    while True:
        # Template URL de descărcare
        url_pagina = f"https://legislatie.just.ro/..." # Completează cu structura ta exactă de URL
        
        print(f"--- [AVANS] An {an} / Pagina {pagina_curenta} ---", flush=True)
        
        succes = False
        ultimul_motiv_esec = ""
        
        # Cele 4 încercări rapide
        for incercare in range(1, MAX_RETRIES_PER_PAGE + 1):
            pauza = PAUSE_BETWEEN_RETRIES * (2 ** (incercare - 1))  # Backoff: 3s, 6s, 12s, 24s
            
            ok, continut, motiv = descarca_pagina_cu_debug(url_pagina)
            
            if ok:
                succes = True
                cicluri_esuate_consecutive = 0  # Resetăm contorul de erori la succes
                
                # Logică stocare XML (Google Drive / Disc)
                # ...
                
                break  # Ieșim din bucla de retry
            else:
                ultimul_motiv_esec = motiv
                print(f"   ⚠️ Încercarea {incercare}/{MAX_RETRIES_PER_PAGE} eșuată pe pagina {pagina_curenta}. Pauză {pauza}s...", flush=True)
                time.sleep(pauza)
        
        if succes:
            pagina_curenta += 1
        else:
            cicluri_esuate_consecutive += 1
            print(f"\n🛑 [Pagină Eșuată] Pagina {pagina_curenta} a eșuat în ciclul {cicluri_esuate_consecutive}/{MAX_FAILED_CYCLES}.", flush=True)
            
            # DACĂ A EȘUAT DE MULTE ORI CONSECUTIV -> SALT DE PAGINĂ (SKIP)
            if cicluri_esuate_consecutive >= MAX_FAILED_CYCLES:
                print(f"⚠️ [SKIP PAGINĂ] Pagina {pagina_curenta} eșuează sistematic! O salvăm în log și SĂRTIM la pagina {pagina_curenta + 1}...", flush=True)
                
                logheaza_pagina_saltata(
                    an=an, 
                    pagina=pagina_curenta, 
                    url=url_pagina, 
                    motiv_detaliat=ultimul_motiv_esec
                )
                
                # Deblocăm bucla prin avansare directă
                pagina_curenta += 1
                cicluri_esuate_consecutive = 0
            else:
                print("   ⏸️ Așteptăm 30 de secunde înainte de a reîncerca aceeași pagină...", flush=True)
                time.sleep(30)


# ==========================================
# MAIN ENTRYPOINT
# ==========================================
def main():
    print("🚀 Script de descărcare XML pornit (cu impresie Chrome via curl_cffi).", flush=True)
    
    # Preluare argumente din linia de comandă (ex: python download_XML.py 2012 2013)
    ani_de_procesat = [2012, 2013]
    if len(sys.argv) >= 3:
        try:
            an_start = int(sys.argv[1])
            an_stop = int(sys.argv[2])
            ani_de_procesat = list(range(an_start, an_stop + 1))
        except ValueError:
            print("⚠️ Argumentele din linia de comandă nu sunt numere valide. Folosim valorile default.", flush=True)

    for an in ani_de_procesat:
        proceseaza_descarcare_an(an, pagina_start=2480 if an == 2012 else 1)

    print("\n✅ Descărcare încheiată cu succes pentru toți anii specificați!", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Procesul a fost întrerupt manual de utilizator (Ctrl+C). Exiting cleanly...", flush=True)
        sys.exit(0)
    except Exception as e:
        # PRINDERE GLOBALĂ A ERORILOR
        print(f"\n💥 [CRITICAL SCRIPT ERROR] A apărut o eroare fatală neprinsă:", flush=True)
        print(f"   Tip Eroare: {type(e).__name__}", flush=True)
        print(f"   Mesaj: {e}", flush=True)
        print("\n📜 Traceback complet:", flush=True)
        traceback.print_exc()
        
        # Ieșire curată cu exit-code 0 pentru menținerea log-urilor în consolă
        sys.exit(0)
