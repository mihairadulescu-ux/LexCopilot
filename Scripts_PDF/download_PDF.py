import os
import sys
import csv
import time
import socket
import json
import urllib.request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Setăm timeout global la nivel de rețea (litere mici conform standardului)
socket.setdefaulttimeout(45.0)

# ======================================================================
# CONFIGURARE ȘI AUTENTIFICARE CLOUD
# ======================================================================
CALE_JURNAL = "jurnal_descarcari_pdf.csv"

def obtine_serviciu_drive():
    """Inițializează conexiunea securizată cu Google Drive API via Service Account."""
    info_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    id_folder_master = os.getenv("DRIVE_FOLDER_XML") # Folderul tău master din Drive
    
    if not info_json or not id_folder_master:
        print("🛑 Eroare critică: Variabilele de mediu (Secretele) lipsesc!")
        sys.exit(1)
        
    try:
        credențiale = service_account.Credentials.from_service_account_info(
            json.loads(info_json),
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=credențiale), id_folder_master
    except Exception as e:
        print(f"🛑 Eroare la autentificarea în Google Drive: {e}")
        sys.exit(1)

# ======================================================================
# LOGICĂ CACHE INTELIGENT (MEMOIZATION)
# ======================================================================
def incarca_fisiere_inexistente_din_jurnal(cale_csv=CALE_JURNAL):
    """
    Citește jurnalul CSV și salvează într-un set în memorie toate fișierele
    care au fost deja confirmate în trecut ca fiind 'Neexistent'.
    """
    fisiere_moarte = set()
    if not os.path.exists(cale_csv):
        return fisiere_moarte
        
    try:
        with open(cale_csv, mode='r', encoding='utf-8') as fh:
            reader = csv.DictReader(fh)
            for rand in reader:
                nume_fisier = rand.get('Fisier', '').strip()
                status = rand.get('Status', '').strip()
                if status == 'Neexistent' and nume_fisier:
                    fisiere_moarte.add(nume_fisier)
        print(f"🧠 [Cache Inteligent] Am încărcat {len(fisiere_moarte)} sufixe moarte din trecut pentru skip instant.")
    except Exception as e:
        print(f"⚠️ Nu s-a putut citi istoricul din CSV pentru skip: {e}")
    return fisiere_moarte

def scrie_in_jurnal(fisier, an, numar, sufix, status, cale_csv=CALE_JURNAL):
    """Scrie sau actualizează starea unui fișier în jurnalul CSV."""
    exista_deja = os.path.exists(cale_csv)
    try:
        with open(cale_csv, mode='a', newline='', encoding='utf-8') as fh:
            campuri = ['Fisier', 'An', 'Numar', 'Sufix', 'Status']
            writer = csv.DictWriter(fh, fieldnames=campuri)
            if not exista_deja:
                writer.writeheader()
            writer.writerow({
                'Fisier': fisier,
                'An': an,
                'Numar': numar,
                'Sufix': sufix,
                'Status': status
            })
    except Exception as e:
        print(f"⚠️ Eroare la scrierea în jurnalul CSV: {e}")

# ======================================================================
# LOGICĂ DE DETECȚIE DRIVE
# ======================================================================
def scaneaza_pdf_existente_in_drive(serviciu, id_folder_master, an_tinta):
    """Scanează Google Drive pentru a vedea ce PDF-uri avem deja descărcate."""
    fisiere_existente = set()
    interogare = f"'{id_folder_master}' in parents and name contains 'MO_PI_{an_tinta}' and mimeType = 'application/pdf' and trashed = false"
    
    try:
        pag_token = None
        while True:
            rezultat = serviciu.files().list(
                q=interogare,
                spaces='drive',
                fields='nextPageToken, files(name)',
                pageSize=1000,
                pageToken=pag_token
            ).execute()
            
            for f in rezultat.get('files', []):
                fisiere_existente.add(f['name'])
                
            pag_token = resultado.get('nextPageToken')
            if not pag_token:
                break
    except Exception as e:
        print(f"⚠️ Eroare la scanarea Drive pentru anul {an_tinta}: {e}")
        
    return fisiere_existente

# ======================================================================
# FUNCȚIA PRINCIPALĂ DE RULARE (PROCESUL INDUSTRIAL)
# ======================================================================
def ruleaza_pipeline_pdf():
    # Citim parametrii trimiși din matricea YAML (ex: "2002 2003")
    if len(sys.argv) < 2:
        print("🛑 Eroare: Lipsesc anii ca parametru în execuție! (Ex: python script.py 2002 2003)")
        sys.exit(1)
        
    ani_argument = sys.argv[1:]
    # Dacă anii vin legați într-un singur string "2002 2003", îi spargem
    if len(ani_argument) == 1 and " " in ani_argument[0]:
        ani_procesare = ani_argument[0].split()
    else:
        ani_procesare = ani_argument

    print(f"🎯 [Matrice PDF] Interceptat interval ani: {ani_procesare}")
    
    # Inițializări
    serviciu_drive, id_folder_master = obtine_serviciu_drive()
    fisiere_de_sarit = incarca_fisiere_inexistente_din_jurnal()

    for an in ani_procesare:
        print(f"\n======================================================================")
        print(f"📅 PORNIRE PROCESARE AN PDF: {an}")
        print(f"======================================================================")
        
        # 1. Vedem ce avem deja în cloud pentru acest an ca să nu suprascriem
        fisiere_in_drive = scaneaza_pdf_existente_in_drive(serviciu_drive, id_folder_master, an)
        print(f"📦 Identificate {len(fisiere_in_drive)} PDF-uri fizice în Drive pentru anul {an}.")

        # Presupunem un algoritm dinamic care verifică până la numărul 1500 per an
        limita_numere = 1500 
        numar_curent = 1
        
        while numar_curent <= limita_numere:
            # Pentru fiecare număr din Monitorul Oficial, verificăm și sufixele
            for sufix in ["", "S", "Bis"]:
                nume_pdf = f"MO_PI_{an}_{numar_curent}{sufix}.pdf"
                
                # A. Pasul de Skip Inteligent (Dacă e marcat mort în CSV)
                if nume_pdf in fisiere_de_sarit:
                    continue
                    
                # B. Pasul de Skip Fizic (Dacă e deja salvat în Google Drive)
                if nume_pdf in fisiere_in_drive:
                    continue

                # C. Dacă nu e nicăieri, înseamnă că e o lacună reală. Îl solicităm de pe Just.ro
                url_sursa = f"http://legislatie.just.ro/Public/AfisareActPdf?id={an}_{numar_curent}{sufix}"
                cale_temporara_locala = f"/tmp/{nume_pdf}"
                
                print(f"⏳ Solicitare server: {nume_pdf}...")
                
                try:
                    # Executăm cererea HTTP
                    urllib.request.urlretrieve(url_sursa, cale_temporara_locala)
                    
                    # Verificăm dacă fișierul descărcat este un PDF real sau o pagină de eroare HTML
                    if os.path.exists(cale_temporara_locala) and os.path.getsize(cale_temporara_locala) > 0:
                        with open(cale_temporara_locala, 'rb') as f_test:
                            antet = f_test.read(4)
                            
                        if antet == b'%PDF':
                            # Este un PDF legitim! Îl trimitem direct în Drive
                            print(f"    🚀 Succes! Se încarcă în Google Drive...")
                            metadata_fisier = {'name': nume_pdf, 'parents': [id_folder_master]}
                            media = MediaFileUpload(cale_temporara_locala, mimetype='application/pdf')
                            
                            serviciu_drive.files().create(body=metadata_fisier, media_body=media, fields='id').execute()
                            scrie_in_jurnal(nume_pdf, an, numar_curent, sufix, "Descarcat")
                            
                            # Curățăm fișierul temporar de pe disc ca să nu umplem mașina virtuală
                            if os.path.exists(cale_temporara_locala):
                                os.remove(cale_temporara_locala)
                        else:
                            # Serverul a întors text/HTML (adică pagina de eroare "Actul nu există")
                            print(f"    ❌ [HTML View] Neexistent pe server.")
                            scrie_in_jurnal(nume_pdf, an, numar_curent, sufix, "Neexistent")
                            if os.path.exists(cale_temporara_locala):
                                os.remove(cale_temporara_locala)
                                
                    time.sleep(0.5) # O mică pauză de curtoazie politicosă pentru server
                    
                except Exception as e:
                    print(f"    🚨 Eroare rețea/server pentru {nume_pdf}: {e}")
                    # Nu îl marcăm ca Neexistent în CSV dacă e eroare pură de rețea (ca să-l mai încerce la rularea următoare)
                    time.sleep(2)
                    
            numar_curent += 1

    print("\n🎉 Rulare completă! Toate lacunele nerezolvate au fost analizate și curățate.")

if __name__ == "__main__":
    ruleaza_pipeline_pdf()
