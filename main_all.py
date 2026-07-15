import os
import sys
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
import requests

# ======================================================================
# ⚙️ CONFIGURARE INTERVAL ANI (Singurul loc pe care trebuie să îl modifici)
# ======================================================================
AN_START = 2000
AN_STOP = 2019

# Calea unde se vor salva fișierele XML descărcate
DIRECTOR_SALVARE = Path("./xml_just_salvate")

# ======================================================================
# CONFIGURARE INTEGRĂRI ȘI PARAMETRI SOAP
# ======================================================================
SOAP_URL = "http://portalquery.just.ro/query.asmx"
SOAP_ACTION = "http://portalquery.just.ro/CautareDosare"

# Template-ul oficial pentru plicul SOAP (XML) cerut de portalquery.just.ro
SOAP_ENVELOPE_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <CautareDosare xmlns="http://portalquery.just.ro/">
      <numarDosar></numarDosar>
      <obiect></obiect>
      <idInstanta></idInstanta>
      <categorieCaz></categorieCaz>
      <numeParte></numeParte>
      <dataStart>{data_start}</dataStart>
      <dataStop>{data_stop}</dataStop>
    </CautareDosare>
  </soap:Body>
</soap:Envelope>"""

def genereaza_intervale_zile(an_start, an_stop):
    """Generează o listă de tupluri (data_start, data_stop) zi de zi pentru intervalul ales."""
    start_date = datetime(an_start, 1, 1)
    end_date = datetime(an_stop, 12, 31)
    
    curent = start_date
    while curent <= end_date:
        # Formatul cerut de SOAP-ul Just.ro este de tipul YYYY-MM-DD
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
        "SOAPAction": SOAP_ACTION,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    statistici = {"succes": 0, "goale": 0, "erori": 0}
    
    # Parcurgem zi cu zi ca să evităm limitarea de 500 de rezultate per interogare
    for d_start, d_stop in genereaza_intervale_zile(AN_START, AN_STOP):
        nume_fisier = DIRECTOR_SALVARE / f"just_dosare_{d_start}.xml"
        
        # Dacă fișierul a fost deja descărcat la o rulare anterioară, îl sărim (resume-friendly)
        if nume_fisier.exists() and nume_fisier.stat().st_size > 500:
            print(f"⏭️ Sărim {d_start} (deja descărcat).")
            continue
            
        print(f"⏳ Interogăm data: {d_start}...", end="", flush=True)
        
        # Înlocuim datele în template-ul SOAP
        payload = SOAP_ENVELOPE_TEMPLATE.format(data_start=d_start, data_stop=d_stop)
        
        incercari = 0
        descarcat_ok = False
        
        while incercari < 3 and not descarcat_ok:
            try:
                # O mică pauză politicoasă între cereri ca să nu ne ia firewall-ul la ochi
                time.sleep(random.uniform(0.5, 1.5))
                
                response = requests.post(SOAP_URL, data=payload, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    xml_content = response.text
                    
                    # Verificăm dacă am primit date reale sau un răspuns gol
                    if "<Dosar>" in xml_content:
                        with open(nume_fisier, "w", encoding="utf-8") as f:
                            f.write(xml_content)
                        print(" [OK - Salvat!]")
                        statistici["succes"] += 1
                    else:
                        # Unele zile (de exemplu weekend-urile sau sărbătorile legale) nu au dosare noi create
                        print(" [Fără dosare]")
                        statistici["goale"] += 1
                        
                    descarcat_ok = True
                else:
                    incercari += 1
                    print(f" (Status {response.status_code}, reîncercăm {incercari}/3)...", end="", flush=True)
                    
            except Exception as e:
                incercari += 1
                print(f" (Eroare: {str(e)[:30]}, reîncercăm {incercari}/3)...", end="", flush=True)
                time.sleep(5)
                
        if not descarcat_ok:
            print(" ❌ Eșuat permanent.")
            statistici["erori"] += 1

    print("\n=======================================================")
    print("🏁 Rularea s-a încheiat!")
    print(f"📈 Statistici finale: {statistici['succes']} zile cu date salvate, {statistici['goale']} zile fără activitate, {statistici['erori']} erori.")
    print("=======================================================")

if __name__ == "__main__":
    descarca_date_just()
