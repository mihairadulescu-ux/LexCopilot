import os
import re
import sys
import json
import requests
from pathlib import Path

# ==============================================================================
# CONFIGURARE TEST
# ==============================================================================
AN_TEST = 1990
PAGINA_TEST = 1
REZULTATE_PER_PAGINA = 10

URL_JUST_API = "https://legislatie.just.ro/api/Search/GetLegi"
URL_SOAP_WSDL = "http://legislatie.just.ro/api/CautareService.svc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/xml, */*",
    "Content-Type": "application/json; charset=utf-8"
}

def test_metoda_json_api(an, pagina):
    """Metoda 1: Interogare prin API-ul JSON/REST wrapper de la Just.ro."""
    print(f"\n🔍 [TEST 1] Încercare interogare API JSON pentru An: {an}, Pagina: {pagina}...")
    
    payload = {
        "SearchAn": str(an),
        "NumarPagina": pagina,
        "RezultatePagina": REZULTATE_PER_PAGINA
    }

    try:
        response = requests.post(URL_JUST_API, json=payload, headers=HEADERS, timeout=15)
        print(f"📡 Status HTTP: {response.status_code}")
        print(f"📊 Dimensiune răspuns: {len(response.content):,} octeți")
        
        if response.status_code == 200:
            text_raw = response.text
            print("\n--- PRIMELE 500 CARACTERE DIN RĂSPUNS ---")
            print(text_raw[:500])
            print("------------------------------------------\n")

            # Salvare fișier de probă
            nume_fisier = f"test_json_{an}_pag{pagina}.xml"
            with open(nume_fisier, "w", encoding="utf-8") as f:
                f.write(text_raw)
            print(f"💾 Fișier salvat local ca: {nume_fisier}")

            # Diagnostic structură
            if "<Legi>" in text_raw or "<SearchModel>" in text_raw:
                print("✅ STRUCTURĂ DETECTATĂ: XML / SOAP Valid!")
            elif '"Legi":' in text_raw or '"SearchModel":' in text_raw:
                print("✅ STRUCTURĂ DETECTATĂ: JSON Valid!")
            else:
                print("⚠️ ATENȚIE: Răspunsul nu conține blocurile standard Așteptate (<Legi> / SearchModel)!")
            
            return True
        else:
            print(f"❌ Eroare la interogare JSON: Status {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Excepție la interogare JSON: {e}")
        return False


def test_metoda_soap_xml(an, pagina):
    """Metoda 2: Interogare directă SOAP XML (pentru a genera XML pur)."""
    print(f"\n🔍 [TEST 2] Încercare interogare SOAP Envelope XML pentru An: {an}, Pagina: {pagina}...")

    soap_headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/ICautareService/GetLegi" # sau actiunea specifica WSDL
    }

    soap_payload = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:temp="http://tempuri.org/">
   <soapenv:Header/>
   <soapenv:Body>
      <temp:GetLegi>
         <temp:searchAn>{an}</temp:searchAn>
         <temp:numarPagina>{pagina}</temp:numarPagina>
         <temp:rezultatePagina>{REZULTATE_PER_PAGINA}</temp:rezultatePagina>
      </temp:GetLegi>
   </soapenv:Body>
</soapenv:Envelope>"""

    try:
        response = requests.post(URL_SOAP_WSDL, data=soap_payload, headers=soap_headers, timeout=15)
        print(f"📡 Status HTTP: {response.status_code}")
        print(f"📊 Dimensiune răspuns: {len(response.content):,} octeți")

        if response.status_code == 200:
            text_raw = response.text
            print("\n--- PRIMELE 500 CARACTERE DIN RĂSPUNS SOAP ---")
            print(text_raw[:500])
            print("----------------------------------------------\n")

            nume_fisier = f"test_soap_{an}_pag{pagina}.xml"
            with open(nume_fisier, "w", encoding="utf-8") as f:
                f.write(text_raw)
            print(f"💾 Fișier salvat local ca: {nume_fisier}")
            return True
        else:
            print(f"❌ Eroare la interogare SOAP directă: Status {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Excepție la interogare SOAP: {e}")
        return False


if __name__ == "__main__":
    print("============================================================")
    print("🚀 PORNIRE TEST PARSARE / INTEROGARE API LEGISLATE.JUST.RO")
    print("============================================================")

    succes_json = test_metoda_json_api(AN_TEST, PAGINA_TEST)
    succes_soap = test_metoda_soap_xml(AN_TEST, PAGINA_TEST)

    print("\n============================================================")
    print("🏁 TEST FINALIZAT!")
    print("Verifică fișierele create local în directorul curent:")
    print(" - test_json_1990_pag1.xml")
    print(" - test_soap_1990_pag1.xml")
    print("============================================================")
