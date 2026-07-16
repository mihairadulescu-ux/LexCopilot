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
AN_CURENT = 2026

URL_TEMPLATE = "https://www.monitoruloficial.ro/emonitor/PDF_baza.php?an={an}&numar={numar}"

def obtine_drive():
    print("🔑 Inițializare conexiune Google Drive API...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_pdf_existente_in_drive(service, an):
    """Identifică toate fișierele PDF din Drive pentru anul respectiv pentru a le pune codul 20 direct."""
    print(f"📂 Scanare fișiere fizice existente în Drive pentru anul {an}...")
    pdf_gasite = set()
    page_token = None
    query = f"'{TARGET_FOLDER_ID}' in parents and name contains 'MO_PI_{an}_' and name contains '.pdf' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query, fields="nextPageToken, files(name)", pageToken=page_token, pageSize=1000,
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
        ).execute()
        for f in response.get("files", []):
            pdf_gasite.add(f["name"])
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
    print(f"📊 S-au detectat {len(pdf_gasite)} fișiere PDF deja salvate în Drive pentru anul {an}.")
    return pdf_gasite

def obtine_sau_creaza_csv(service, an):
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
    else:
        # Dacă nu există deloc registrul, generăm unul curat cu 0 peste tot
        matrice = []
        for n in range(1, 1501):
            matrice.append({"numar": str(n), "simplu": "0", "bis": "0", "tris": "0", "quatro": "0", "s": "0"})
        cale_temp = f"temp_{nume_csv}"
        with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["numar", "simplu", "bis", "tris", "quatro", "s"])
            writer.writeheader()
            writer.writerows(matrice)
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        metadata = {'name': nume_csv, 'parents': [TARGET_FOLDER_ID]}
        nou_fisier = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
        os.remove(cale_temp)
        return nou_fisier["id"], matrice

def salveaza_csv_in_drive(service, file_id, nume_csv, date_rows):
    cale_temp = f"temp_save_{nume_csv}"
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["numar", "simplu", "bis", "tris", "quatro", "s"])
        writer.writeheader()
        writer.writerows(date_rows)
    media = MediaFileUpload(cale_temp, mimetype="text/csv", resumable=True)
    service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
    os.remove(cale_temp)
    print(f"💾 Registru complet actualizat și salvat în Drive: {nume_csv}")

def descarca_monitoare():
    print("🚀 Pornire script radical sync_simple...")
    if not TARGET_FOLDER_ID:
        print("❌ EROARE: DRIVE_FOLDER_PDF nu este setat!")
        sys.exit(1)
        
    service = obtine_drive()
    
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for an in YEARS_TO_PROCESS:
            print(f"\n--- 📅 Sincronizare Radicală Anul {an} ---")
            nume_csv = f"status_{an}.csv"
            
            # Pasul 1: Scanăm ce fișiere avem cu adevărat în Drive
            pdf_existente = listeaza_pdf_existente_in_drive(service, an)
            
            # Pasul 2: Preluăm registrul CSV
            file_id, rows = obtine_sau_creaza_csv(service, an)
            modificari = False
            rows_dict = {int(r["numar"]): r for r in rows}
            
            # Pasul 3: Resemnalizăm matricea conform realității fizice din Drive
            for n in range(1, 1501):
                nume_pdf_simplu = f"MO_PI_{an}_{n}.pdf"
                
                if nume_pdf_simplu in pdf_existente:
                    if rows_dict[n]["simplu"] != "20":
                        rows_dict[n]["simplu"] = "20"
                        modificari = True
                else:
                    # Dacă nu există în Drive și nu a fost deja marcat ca eșec critic (15), îl aducem la starea de verificare (0)
                    if rows_dict[n]["simplu"] != "15":
                        if rows_dict[n]["simplu"] != "0":
                            rows_dict[n]["simplu"] = "0"
                            modificari = True
            
            eroare_consecutiva_404 = 0
            
            # Pasul 4: Scanare curată de la 1 la 1500
            for numar in range(1, 1501):
                if eroare_consecutiva_404 >= 15:
                    print(f"🛑 Oprim scanarea pe anul {an}: am atins granița publicațiilor reale (15 erori consecutive).")
                    break
                    
                row = rows_dict[numar]
                stare_simpla = int(row["simplu"])
                
                # Dacă e confirmat valid în Drive (20) sau eșec critic (15), resetăm contorul de 404 și mergem mai departe
                if stare_simpla in [15, 20]:
                    eroare_consecutiva_404 = 0
                    continue
                
                # Dacă starea este 0, înseamnă că fișierul lipsește din Drive, deci îl căutăm pe serverul oficial
                if stare_simpla == 0:
                    url = URL_TEMPLATE.format(an=an, numar=numar)
                    nume_pdf = f"MO_PI_{an}_{numar}.pdf"
                    try:
                        print(f"🔍 Interogare server pentru monitorul lipsă: {nume_pdf}...")
                        r = client.get(url)
                        
                        if r.status_code == 200 and len(r.content) > 1000:
                            cale_pdf = f"temp_{nume_pdf}"
                            with open(cale_pdf, "wb") as f_pdf:
                                f_pdf.write(r.content)
                            media = MediaFileUpload(cale_pdf, mimetype="application/pdf")
                            metadata = {'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]}
                            service.files().create(body=metadata, media_body=media, supportsAllDrives=True).execute()
                            os.remove(cale_pdf)
                            
                            row["simplu"] = "20"
                            modificari = True
                            eroare_consecutiva_404 = 0
                            print(f"   ✅ [DESCARCAT ȘI SALVAT] {nume_pdf}")
                        else:
                            # În caz de 404 sau fișier gol de pe server, setăm eșec critic 15
                            row["simplu"] = "15"
                            # Propagăm automat 10 pe sufixe, fiindcă numărul de bază nu există pe server
                            for col in ["bis", "tris", "quatro", "s"]:
                                row[col] = "10"
                            
                            modificari = True
                            eroare_consecutiva_404 += 1
                            print(f"   ⚠️ Inexistent pe server (HTTP {r.status_code}). Marcat definitiv cu status 15.")
                            
                        time.sleep(random.uniform(0.1, 0.3))
                    except Exception as e:
                        print(f"   ❌ Eroare rețea/conexiune la {nume_pdf}: {e}. Lăsăm pe status 0 pentru reîncercare.")
                        eroare_consecutiva_404 += 1
                        time.sleep(2.0)
            
            if modificari:
                salveaza_csv_in_drive(service, file_id, nume_csv, list(rows_dict.values()))
            else:
                print(f"ℹ️ Registrul pentru anul {an} este deja perfect sincronizat cu fișierele din Drive.")

if __name__ == "__main__":
    descarca_monitoare()
