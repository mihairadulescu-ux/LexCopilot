import os
import sys
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
import requests

# ======================================================================
# ⚙️ CONFIGURARE INTERVAL ANI
# ======================================================================
AN_START = 2000
AN_STOP = 2019

# Calea unde se vor salva fișierele XML descărcate
DIRECTOR_SALVARE = Path("./xml_just_salvate")

# ======================================================================
# CONFIGURARE PARAMETRI SOAP (HTTP Simplu - exact cum vrea serverul Just)
# ======================================================================
SOAP_URL = "http://portalquery.just.ro/query.asmx"
SOAP_ACTION = "http://portalquery.just.ro/CautareDosare"

# Plicul XML corect conform specificațiilor oficiale (.NET ASMX)
SOAP_ENVELOPE_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <CautareDosare xmlns="http://portalquery.just.ro/">
      <numarDosar></numarDosar>
      <obiectDosar></obiectDosar>
      <numeParte></numeParte>
      <institutie xsi:nil="true" />
      <dataStart>{data_start}T00:00:00</dataStart>
      <dataStop>{data_stop}T23:59:59</dataStop>
    </CautareDosare>
  </soap:Body>
</soap:Envelope>"""

def genereaza_intervale_zile(an_start, an_stop):
    """Generează o listă de tupluri zi de zi (YYYY-MM-DD)."""
    start_date = datetime(an_start, 1, 1)
    end_date = datetime(an_stop, 12, 31)
    
    curent = start_date
    while curent <= end_date:
        data_str = curent.strftime("%Y-%m-%d")
        yield data_str, data_str
        curent += timedelta(days=1)

def descarca_date_just():
    DIRECTOR_SALVARE.mkdir(exist_ok=True)
    
    print(f"🚀 Pornire crawler Just.ro (SOAP)...")
    print(f"📅 Interval setat: {AN_START} - {AN_STOP}")
    print(f"📂 Salvare în: {DIRECTOR_SALVARE.resolve()}\n")
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{SOAP_ACTION}"', # SOAPAction în ghilimele pentru standardul .NET
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    statistici = {"succes": 0, "goale": 0, "erori": 0}
    
    for d_start, d_stop in genereaza_intervale_zile(AN_START, AN_STOP):
        nume_fisier = DIRECTOR_SALVARE / f"just_dosare_{d_start}.xml"
        
        # Sărim fișierele deja descărcate
        if nume_fisier.exists() and nume_fisier.stat().st_size > 500:
            print(f"⏭️ Sărim {d_start} (deja descărcat).")
            continue
            
        print(f"⏳ Interogăm data: {d_start}...", end="", flush=True)
        
        payload = SOAP_ENVELOPE_TEMPLATE.format(data_start=d_start, data_stop=d_stop)
        
        incercari = 0
        descarcat_ok = False
        
        while incercari < 3 and not descarcat_ok:
            try:
                # O mică pauză variabilă să evităm limitările de rată
                time.sleep(random.uniform(0.5, 1.2))
                
                # Apel direct HTTP
                response = requests.post(SOAP_URL, data=payload, headers=headers, timeout=25)
                
                if response.status_code == 200:
                    xml_content = response.text
                    
                    if "<Dosar>" in xml_content or "<Dosar " in xml_content:
                        with open(nume_fisier, "w", encoding="utf-8") as f:
                            f.write(xml_content)
                        print(" [OK - Salvat!]")
                        statistici["succes"] += 1
                    else:
                        print(" [Fără dosare]")
                        statistici["goale"] += 1
                        
                    descarcat_ok = True
                else:
                    incercari += 1
                    print(f" (Status {response.status_code}, reîncercăm {incercari}/3)...", end="", flush=True)
                    time.sleep(2)
                    
            except Exception as e:
                incercari += 1
                print(f" (Eroare rețea: {str(e)[:40]}, reîncercăm {incercari}/3)...", end="", flush=True)
                time.sleep(4)
                
        if not descarcat_ok:
            print(" ❌ Eșuat permanent.")
            statistici["erori"] += 1

    print("\n=======================================================")
    print("🏁 Rularea s-a încheiat!")
    print(f"📈 Statistici finale: {statistici['succes']} zile cu date, {statistici['goale']} fără activitate, {statistici['erori']} erori.")
    print("=======================================================")

if __name__ == "__main__":
    descarca_date_just()
