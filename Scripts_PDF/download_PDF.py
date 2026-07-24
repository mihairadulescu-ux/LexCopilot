# filename: Scripts_PDF/download_PDF.py
# Scop

import os
import sys
import csv
import time
import socket
import json
import requests

# ======================================================================
# CONFIGURARE CRITICĂ PENTRU AFIȘARE LOGURI LIVE (NO-BUFFERING)
# ======================================================================
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def log(mesaj=""):
    """Afiseaza mesajul si forteaza trimiterea instantanee catre consola GitHub Actions."""
    print(mesaj, flush=True)
    sys.stdout.flush()

socket.setdefaulttimeout(45.0)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Antet-uri HTTP pentru a simula un browser real
HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
}

CALE_JURNAL = "jurnal_descarcari_pdf.csv"

def obtine_serviciu_drive():
    info_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    id_folder_master = os.getenv("DRIVE_FOLDER_PDF")
    
    if not info_json or not id_folder_master:
        log("🛑 Eroare critică: Variabilele de mediu (Secretele) lipsesc!")
        sys.exit(1)
        
    try:
        credențiale = service_account.Credentials.from_service_account_info(
            json.loads(info_json),
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=credențiale, cache_discovery=False), id_folder_master
    except Exception as e:
        log(f"🛑 Eroare la autentificarea în Google Drive: {e}")
        sys.exit(1)

def incarca_fisiere_inexistente_din_jurnal(cale_csv=CALE_JURNAL):
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
        log(f"🧠 [Cache Inteligent] Am încărcat {len(fisiere_moarte)} sufixe moarte din trecut pentru skip instant.")
    except Exception as e:
        log(f"⚠️ Nu s-a putut citi istoricul din CSV pentru skip: {e}")
    return fisiere_moarte

def scrie_in_jurnal(fisier, an, numar, sufix, status, cale_csv=CALE_JURNAL):
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
        log(f"⚠️ Eroare la scrierea în jurnalul CSV: {e}")

def scaneaza_pdf_existente_in_drive(serviciu, id_folder_master, an_tinta):
    fisiere_existente = set()
    interogare = f"'{id_folder_master}' in parents and name contains 'MO_PI_{an_tinta}' and mimeType = 'application/pdf' and trashed = false"
    
    log(f"🔍 [Drive API] Scanăm folderele pentru anul {an_tinta}...")
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
            
            fisiere_lot = rezultat.get('files', [])
            for f in fisiere_lot:
                fisiere_existente.add(f['name'])
                
            pag_token = rezultat.get('nextPageToken')
            log(f"   ├─ Pachet scanat: +{len(fisiere_lot)} PDF-uri găsite (Total acum: {len(fisiere_existente)})")
            
            if not pag_token:
                break
    except Exception as e:
        log(f"⚠️ Eroare la scanarea Drive pentru anul {an_tinta}: {e}")
        
    return fisiere_existente

def ruleaza_pipeline_pdf():
    log("======================================================================")
    log("🚀 PORNIRE PIPELINE DESCARCARE PDF MO_PI")
    log("======================================================================")

    if len(sys.argv) < 2:
        log("🛑 Eroare: Lipsesc anii ca parametru în execuție!")
        sys.exit(1)
        
    ani_argument = sys.argv[1:]
    if len(ani_argument) == 1 and " " in ani_argument[0]:
        ani_procesare = ani_argument[0].split()
    else:
        ani_procesare = ani_argument

    log(f"🎯 [Matrice PDF] Interceptat interval ani: {ani_procesare}")
    
    serviciu_drive, id_folder_master = obtine_serviciu_drive()
    fisiere_de_sarit = incarca_fisiere_inexistente_din_jurnal()

    # Creăm o sesiune HTTP reutilizabilă
    session = requests.Session()
    session.headers.update(HEADERS_BROWSER)

    for an in ani_procesare:
        log("\n======================================================================")
        log(f"📅 PORNIRE PROCESARE AN PDF: {an}")
        log("======================================================================")
        
        fisiere_in_drive = scaneaza_pdf_existente_in_drive(serviciu_drive, id_folder_master, an)
        log(f"📦 Identificate {len(fisiere_in_drive)} PDF-uri fizice în Drive pentru anul {an}.")

        limita_numere = 1500 
        numar_curent = 1
        
        while numar_curent <= limita_numere:
            for sufix in ["", "S", "Bis"]:
                nume_pdf = f"MO_PI_{an}_{numar_curent}{sufix}.pdf"
                
                if nume_pdf in fisiere_de_sarit or nume_pdf in fisiere_in_drive:
                    continue

                # Folosim HTTPS cu fallback
                url_sursa = f"https://legislatie.just.ro/Public/AfisareActPdf?id={an}_{numar_curent}{sufix}"
                cale_temporara_locala = f"/tmp/{nume_pdf}"
                
                log(f"⏳ Solicitare server: {nume_pdf}...")
                
                try:
                    resp = session.get(url_sursa, timeout=20, stream=True)
                    
                    if resp.status_code == 200:
                        content_type = resp.headers.get("Content-Type", "")
                        
                        # Salvăm conținutul
                        with open(cale_temporara_locala, "wb") as f_out:
                            for chunk in resp.iter_content(chunk_size=8192):
                                f_out.write(chunk)
                        
                        # Verificăm dacă e PDF valid
                        if os.path.exists(cale_temporara_locala) and os.path.getsize(cale_temporara_locala) > 0:
                            with open(cale_temporara_locala, 'rb') as f_test:
                                antet = f_test.read(4)
                                
                            if antet == b'%PDF':
                                log(f"    🚀 Succes! Se încarcă în Google Drive...")
                                metadata_fisier = {'name': nume_pdf, 'parents': [id_folder_master]}
                                media = MediaFileUpload(cale_temporara_locala, mimetype='application/pdf')
                                
                                serviciu_drive.files().create(body=metadata_fisier, media_body=media, fields='id').execute()
                                scrie_in_jurnal(nume_pdf, an, numar_curent, sufix, "Descarcat")
                            else:
                                log(f"    ❌ [HTML View / Incomplet] Neexistent pe server.")
                                scrie_in_jurnal(nume_pdf, an, numar_curent, sufix, "Neexistent")
                                
                            if os.path.exists(cale_temporara_locala):
                                os.remove(cale_temporara_locala)
                    else:
                        log(f"    ❌ HTTP {resp.status_code} - Neexistent.")
                        scrie_in_jurnal(nume_pdf, an, numar_curent, sufix, "Neexistent")

                    time.sleep(0.3)
                    
                except Exception as e:
                    log(f"    🚨 Eroare rețea/server pentru {nume_pdf}: {e}")
                    time.sleep(1.5)
                    
            numar_curent += 1

    log("\n🎉 Rulare completă! Toate lacunele nerezolvate au fost analizate și curățate.")

if __name__ == "__main__":
    ruleaza_pipeline_pdf()
