import os
import sys
import json
import time
import random
import csv
import io
import httpx
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")
YEARS_TO_PROCESS = [int(y) for y in os.getenv("YEARS", "2026").split(",")]

URL_TEMPLATE = "https://www.monitoruloficial.ro/emonitor/PDF_baza.php?an={an}&numar={numar}{sufix}"

def obtine_drive():
    print("🔑 [Sufixe] Inițializare conexiune Google Drive API...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_sufixe_existente_in_drive(service, an):
    """Scanează Drive pentru a găsi toate sufixele descărcate deja în trecut."""
    print(f"📂 [Sufixe] Scanare fișiere fizice existente în Drive pentru anul {an}...")
    sufixe_gasite = set()
    page_token = None
    query = f"'{TARGET_FOLDER_ID}' in parents and name contains 'MO_PI_{an}_' and name contains '.pdf' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query, fields="nextPageToken, files(name)", pageToken=page_token, pageSize=1000,
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
        ).execute()
        for f in response.get("files", []):
            nume = f["name"]
            # Păstrăm doar numele fișierelor care conțin litere în sufix (ex: MO_PI_2024_12Bis.pdf)
            # Eliminăm extensia .pdf pentru mapare ușoară
            sufixe_gasite.add(nume.replace(".pdf", ""))
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
    print(f"📊 [Sufixe] Detectate {len(sufixe_gasite)} ediții speciale fizice în Drive pentru anul {an}.")
    return sufixe_gasite

def obtine_csv(service, an):
    nume_csv = f"status_{an}.csv"
    query = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_csv}' and trashed = false"
    existente = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
    ).execute().get("files", [])
    if existente:
        file_id = existente[0]["id"]
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        linii = fh.getvalue().decode("utf-8").splitlines()
        reader = list(csv.DictReader(linii))
        return file_id, reader
    return None, None

def salveaza_csv_in_drive(service, file_id, nume_csv, date_rows):
    cale_temp = f"temp_save_suf_{nume_csv}"
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["numar", "simplu", "bis", "tris", "quatro", "s"])
        writer.writeheader()
        writer.writerows(date_rows)
    media = MediaFileUpload(cale_temp, mimetype="text/csv", resumable=True)
    service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
    os.remove(cale_temp)
    print(f"💾 [Sufixe] Registru actualizat cu succes în Drive: {nume_csv}")

def descarca_sufixe():
    print("🚀 Pornire script radical sync_sufixe...")
    if not TARGET_FOLDER_ID:
        print("❌ EROARE: DRIVE_FOLDER_PDF nu este setat!")
        sys.exit(1)
    service = obtine_drive()
    
    # Definirea sufixelor în ordine ierarhică strictă
    config_sufixe = [
        {"col": "bis", "url": "Bis"},
        {"col": "tris", "url": "Tris"},
        {"col": "quatro", "url": "Quatro"},
        {"col": "s", "url": "S"}
    ]
    
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for an in YEARS_TO_PROCESS:
            print(f"\n--- 📅 Sincronizare Secundare Anul {an} ---")
            nume_csv = f"status_{an}.csv"
            
            # Pasul 1: Citire fișiere fizice din Drive
            sufixe_fizice = listeaza_sufixe_existente_in_drive(service, an)
            
            # Pasul 2: Preluare registru CSV (sincronizat deja de scriptul simplu)
            file_id, rows = obtine_csv(service, an)
            if not rows:
                print(f"⚠️ Registrul {nume_csv} nu există. Rulați mai întâi sync_simple.py!")
                continue
                
            modificari = False
            rows_dict = {int(r["numar"]): r for r in rows}
            
            # Pasul 3: Scanare matrice 1-1500
            for numar in range(1, 1501):
                row = rows_dict[numar]
                
                # Regula de Aur 1: Dacă numărul SIMPLU nu există (15), sufixele sunt deja 10. Trecem peste.
                if row["simplu"] == "15":
                    continue
                    
                # Regula de Aur 2: Procesăm sufixele DOAR dacă numărul simplu este confirmat descărcat (20)
                if row["simplu"] == "20":
                    
                    # Parcurgem sufixele în ordine: Bis -> Tris -> Quatro -> S
                    for idx, cfg in enumerate(config_sufixe):
                        col_curenta = cfg["col"]
                        sufix_url = cfg["url"]
                        nume_identificare = f"MO_PI_{an}_{numar}{sufix_url}"
                        
                        # Cazul A: Sufixul există deja fizic în Drive -> Îi punem status 20 direct
                        if nume_identificare in sufixe_fizice:
                            if row[col_curenta] != "20":
                                row[col_curenta] = "20"
                                modificari = True
                            continue # Mergem la următorul sufix din listă (ex: de la Bis la Tris)
                        
                        # Cazul B: Nu există în Drive. Evaluăm starea din CSV.
                        stare_curenta = int(row[col_curenta])
                        
                        # Dacă a fost deja marcat ca inexistent confirmat (10) sau e deja 20, nu facem nimic
                        if stare_curenta in [10, 20]:
                            # Dacă e 10, înseamnă că propagarea a avut loc deja, oprim verificarea sufixelor superioare
                            if stare_curenta == 10:
                                break
                            continue
                            
                        # Dacă starea este un contor curat sau parțial (0, 1), avem voie să îl testăm pe server (max 2 încercări)
                        if 0 <= stare_curenta <= 1:
                            url = URL_TEMPLATE.format(an=an, numar=numar, sufix=sufix_url)
                            nume_pdf = f"{nume_identificare}.pdf"
                            
                            try:
                                print(f"🔍 [Încercare {stare_curenta}] Verificare server pentru sufix: {nume_pdf}...")
                                r = client.get(url)
                                
                                if r.status_code == 200 and len(r.content) > 1000:
                                    cale_pdf = f"temp_{nume_pdf}"
                                    with open(cale_pdf, "wb") as f_pdf:
                                        f_pdf.write(r.content)
                                    media = MediaFileUpload(cale_pdf, mimetype="application/pdf")
                                    metadata = {'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]}
                                    service.files().create(body=metadata, media_body=media, supportsAllDrives=True).execute()
                                    os.remove(cale_pdf)
                                    
                                    row[col_curenta] = "20"
                                    modificari = True
                                    print(f"   ✅ [DESCARCAT SUFIX] {nume_pdf}")
                                    # Continuăm bucla, deoarece acest sufix existând, cel următor are dreptul să fie verificat
                                    continue 
                                else:
                                    # Eșec descărcare (404 sau fișier gol)
                                    stare_noua = stare_curenta + 1
                                    row[col_curenta] = str(stare_noua)
                                    modificari = True
                                    print(f"   ❌ Sufix negăsit pe server. Stare incrementată la: {stare_noua}")
                                    
                                    # Dacă am consumat cele 2 încercări (starea a ajuns la 2), îl declarăm inexistent (10)
                                    if stare_noua == 2:
                                        print(f"   ⚠️ [Propagare] Sufixul {sufix_url} nu există după 2 încercări. Blocăm automat restul sufixelor superioare.")
                                        # Aplicăm regula ta radicală: marcăm cu 10 sufixul curent și TOATE cele care urmează după el!
                                        for i_rest in range(idx, len(config_sufixe)):
                                            row[config_sufixe[i_rest]["col"]] = "10"
                                        break # Întrerupem imediat verificarea altor sufixe pentru acest număr!
                                        
                                time.sleep(random.uniform(0.1, 0.2))
                            except Exception as e:
                                print(f"   ❌ Eroare rețea la sufixul {nume_pdf}: {e}. Lăsăm contorul pe loc.")
                                time.sleep(1.0)
                                break # Oprim examinarea pe acest număr la erori de rețea globale ca să nu alterăm matricea
            
            if modificari:
                salveaza_csv_in_drive(service, file_id, nume_csv, list(rows_dict.values()))
            else:
                print(f"ℹ️ Sufixele pentru anul {an} sunt complet aliniate.")

if __name__ == "__main__":
    descarca_sufixe()
