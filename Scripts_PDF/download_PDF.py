import os
import sys
import time
import random
import io
import json
import csv
import re
from pathlib import Path
import httpx
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

# Folderul unificat unde stau PDF-urile și CSV-urile de status
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")

START_YEAR = int(os.getenv("START_YEAR", "2000"))
END_YEAR = int(os.getenv("END_YEAR", "2026"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
]

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def incarc_registru_an(service, folder_id, an):
    registru_local = {}
    nume_csv = f"status_{an}.csv"
    query = f"'{folder_id}' in parents and name = '{nume_csv}' and trashed = false"
    
    try:
        files = service.files().list(
            q=query, spaces='drive', fields='files(id)', 
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives"
        ).execute().get('files', [])
        
        if files:
            request = service.files().get_media(fileId=files[0]['id'])
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            
            reader = csv.reader(io.StringIO(fh.getvalue().decode('utf-8')))
            header = next(reader, None)
            
            for rand in reader:
                if len(rand) >= 3:
                    nr_baza = rand[0]
                    sufix = rand[1]
                    status = rand[2]
                    cheie = f"MO_PI_{an}_{nr_baza}{sufix}.pdf" if sufix else f"MO_PI_{an}_{nr_baza}.pdf"
                    registru_local[cheie] = status
    except Exception as e:
        print(f"{GALBEN}⚠️ Nu s-a putut citi registrul {nume_csv} ({e}). Pornim la rece pe acest an.{RESET}", flush=True)
    
    return registru_local

def salveaza_registru_an(service, folder_id, an, registru_local):
    nume_csv = f"status_{an}.csv"
    print(f"💾 Actualizare registru Cloud [{nume_csv}]...", flush=True)
    
    randuri_csv = []
    for nume_fisier, status in sorted(registru_local.items()):
        m = re.search(r"MO_PI_(\d{4})_([A-Za-z0-9]+)\.pdf", nume_fisier)
        if m:
            numar_complet = m.group(2)
            match_baza = re.match(r"^(\d+)", numar_complet)
            if match_baza:
                nr_baza = match_baza.group(1)
                sufix = numar_complet[len(nr_baza):]
                randuri_csv.append([nr_baza, sufix, status, "0" if status == "neexistent" else "recalculat", ""])

    cale_temp = f"temp_sync_{nume_csv}"
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
        writer.writerows(randuri_csv)
        
    try:
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        query = f"'{folder_id}' in parents and name = '{nume_csv}' and trashed = false"
        existing = service.files().list(
            q=query, spaces='drive', fields='files(id)', 
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives"
        ).execute().get('files', [])
        
        if existing:
            service.files().update(fileId=existing[0]['id'], media_body=media, supportsAllDrives=True).execute()
        else:
            meta = {"name": nume_csv, "parents": [folder_id]}
            service.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
        
        if os.path.exists(cale_temp):
            os.remove(cale_temp)
        print(f"    ✅ Sincronizat cu succes direct în folder.", flush=True)
    except Exception as e:
        print(f"{ROSU}❌ Eroare la salvarea CSV-ului {nume_csv}: {e}{RESET}", flush=True)

def ruleaza_sincronizare_matriceala(an_start, an_stop):
    if not TARGET_FOLDER_ID:
        print(f"{ROSU}🛑 Eroare configurare: DRIVE_FOLDER_PDF nu este definit în mediu!{RESET}", flush=True)
        return

    url_template = "https://monitoruloficial.ro/Monitorul-Oficial--PI--{numar}--{an}.html"
    service = obtine_drive()
    
    director_temp = Path("./temp_pdf")
    director_temp.mkdir(exist_ok=True)
    timeout_resilient = httpx.Timeout(timeout=120.0, connect=20.0)
    
    MAX_NUMERE_AN = 1350

    for an in range(an_start, an_stop + 1):
        print(f"\n{VERDE}🔄 Pasul 1: Încărcare registru anexat pentru anul {an}...{RESET}", flush=True)
        registru_an = incarc_registru_an(service, TARGET_FOLDER_ID, an)
        print(f"📊 Înregistrări găsite în indexul anului {an}: {len(registru_an)}", flush=True)
        
        coada_an = []
        modificari_detectate = False
        
        for n in range(1, MAX_NUMERE_AN + 1):
            f_simplu = f"MO_PI_{an}_{n}.pdf"
            
            if f_simplu not in registru_an or registru_an[f_simplu] == "":
                coada_an.append({"numar": str(n), "nume": f_simplu})
                continue
                
            if registru_an[f_simplu] == "descarcat":
                f_bis = f"MO_PI_{an}_{n}Bis.pdf"
                f_special = f"MO_PI_{an}_{n}S.pdf"
                
                if f_special not in registru_an or registru_an[f_special] == "":
                    coada_an.append({"numar": f"{n}S", "nume": f_special})
                
                if f_bis not in registru_an or registru_an[f_bis] == "":
                    coada_an.append({"numar": f"{n}Bis", "nume": f_bis})
                elif registru_an[f_bis] == "descarcat":
                    f_tris = f"MO_PI_{an}_{n}Tris.pdf"
                    if f_tris not in registru_an or registru_an[f_tris] == "":
                        coada_an.append({"numar": f"{n}Tris", "nume": f_tris})
                    elif registru_an[f_tris] == "descarcat":
                        f_quater = f"MO_PI_{an}_{n}Quater.pdf"
                        if f_quater not in registru_an or registru_an[f_quater] == "":
                            coada_an.append({"numar": f"{n}Quater", "nume": f_quater})

        total_an = len(coada_an)
        if total_an == 0:
            print(f"🎉 Toate elementele ierarhice pentru anul {an} sunt la zi în CSV. Trecem la următorul an.", flush=True)
            continue
            
        print(f"🚀 Începe verificarea a {total_an} fișiere lipsă dintr-un total mapat al anului {an}...", flush=True)
        
        for idx, item in enumerate(coada_an, 1):
            nume_pdf = item["nume"]
            url = url_template.format(numar=item["numar"], an=an)
            
            print(f"⏳ [{idx}/{total_an}] Solicitare server: {nume_pdf}...", flush=True)
            time.sleep(random.uniform(0.5, 1.2))
            
            try:
                headers = {"User-Agent": random.choice(USER_AGENTS), "Referer": "https://monitoruloficial.ro/"}
                with httpx.Client(headers=headers, timeout=timeout_resilient, follow_redirects=True) as client:
                    response = client.get(url)
                    
                    if response.status_code == 404:
                        print(f"    ❌ [404] Neexistent sigur pe server. Notat ca neexistent.", flush=True)
                        registru_an[nume_pdf] = "neexistent"
                        modificari_detectate = True
                        continue
                    
                    if response.status_code != 200:
                        print(f"    ⚠️ [Eroare Server {response.status_code}] Skip. Nu se modifică starea în CSV.", flush=True)
                        continue
                        
                    content_type = response.headers.get("Content-Type", "").lower()
                    
                    # Verificare binară
                    if "application/pdf" in content_type or len(response.content) > 30000:
                        # --- BLOC DE EXAMINARE OCTEȚI PDF REAL ---
                        total_bytes = len(response.content)
                        # Extragem primii 5 bytes în format text brut și hexazecimal
                        magic_bytes_brut = response.content[:5]
                        magic_bytes_hex = " ".join(f"{b:02x}" for b in magic_bytes_brut)
                        magic_bytes_text = magic_bytes_brut.decode('utf-8', errors='ignore')
                        
                        # Prindem un mic extras din header (primele 150 de caractere text)
                        header_snippet = response.content[:150].decode('utf-8', errors='ignore').replace('\n', ' ').replace('\r', '')
                        
                        print(f"    🔬 [ANATOMIE PDF] Mărime: {total_bytes} bytes ({total_bytes/1024/1024:.2f} MB)")
                        print(f"    ↳ Magic Bytes (Hex): {VERDE}{magic_bytes_hex}{RESET} | Text: {VERDE}{magic_bytes_text}{RESET}")
                        print(f"    ↳ Extras Header: {GALBEN}{header_snippet}...{RESET}", flush=True)
                        # ----------------------------------------
                        
                        cale_l = director_temp / nume_pdf
                        with open(cale_l, "wb") as f_out:
                            f_out.write(response.content)
                            
                        media = MediaFileUpload(str(cale_l), mimetype='application/pdf', resumable=True)
                        meta_drive = {'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]}
                        service.files().create(body=meta_drive, media_body=media, supportsAllDrives=True).execute()
                        
                        cale_l.unlink()
                        print(f"    📥 {VERDE}[DESCARCAT]{RESET} Salvat PDF real în Shared Drive! ✅", flush=True)
                        registru_an[nume_pdf] = "descarcat"
                        modificari_detectate = True
                    else:
                        text_primit = response.text
                        if "flowpaper_viewer" in text_primit or "flowpaper" in text_primit or "<title>Monitorul Oficial" in text_primit:
                            print(f"    ❌ [HTML Empty Viewer] Interfață fără document binar. Notat ca neexistent.", flush=True)
                            registru_an[nume_pdf] = "neexistent"
                            modificari_detectate = True
                        else:
                            print(f"    ⚠️ [HTML Necunoscut / Mentenanță] Structură text nesigură. Skip.", flush=True)
                            continue
                        
            except Exception as e:
                print(f"    ❌ [Eroare Rețea] {str(e)[:70]}. Va fi reîncercat la rularea următoare.", flush=True)
                continue
        
        if modificari_detectate:
            salveaza_registru_an(service, TARGET_FOLDER_ID, an, registru_an)

    print(f"\n{VERDE}🎉 Procesul global de sincronizare unificată a PDF-urilor s-a finalizat structural!{RESET}\n")

if __name__ == "__main__":
    argumente = [int(arg) for arg in sys.argv[1:] if arg.isdigit()]
    an_s = argumente[0] if len(argumente) >= 1 else START_YEAR
    an_f = argumente[1] if len(argumente) >= 2 else (argumente[0] if len(argumente) == 1 else END_YEAR)
    
    print(f"🎯 [Config] Sincronizare pe intervalul de ani: {an_s} - {an_f}", flush=True)
    ruleaza_sincronizare_matriceala(an_s, an_f)
