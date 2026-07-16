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
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

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
    print(f"💾 [Sufixe] Registru actualizat: {nume_csv}")

def descarca_sufixe():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE: DRIVE_FOLDER_PDF nu este setat!")
        sys.exit(1)
    service = obtine_drive()
    
    config_sufixe = [
        {"col": "bis", "url": "Bis"},
        {"col": "tris", "url": "Tris"},
        {"col": "quatro", "url": "Quatro"},
        {"col": "s", "url": "S"}
    ]
    
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for an in YEARS_TO_PROCESS:
            print(f"\n--- 📅 Sincronizare sufixe Anul {an} ---")
            nume_csv = f"status_{an}.csv"
            file_id, rows = obtine_csv(service, an)
            if not rows:
                continue
            modificari = False
            rows_dict = {int(r["numar"]): r for r in rows}
            
            for numar in range(1, 1501):
                row = rows_dict[numar]
                
                # Dacă numărul simplu este eșuat complet (15), sufixele sunt deja forțate la 10
                if row["simplu"] == "15":
                    continue
                    
                # Procesăm doar dacă numărul de bază există în siguranță (20)
                if row["simplu"] == "20":
                    for idx, cfg in enumerate(config_sufixe):
                        col = cfg["col"]
                        sufix_url = cfg["url"]
                        stare_curenta = int(row[col])
                        
                        if stare_curenta in [10, 20]:
                            if stare_curenta == 10:
                                break # Dacă Bis e inexistent, ne oprim complet pe sufixele superioare
                            continue
                            
                        # Încercăm descărcarea doar pentru stările intermediare (maximum 2 încercări: 0 și 1)
                        if 0 <= stare_curenta <= 1:
                            url = URL_TEMPLATE.format(an=an, numar=numar, sufix=sufix_url)
                            nume_pdf = f"MO_PI_{an}_{numar}{sufix_url}.pdf"
                            try:
                                print(f"🔍 [Încercare {stare_curenta}] Descărcare sufix {nume_pdf}...")
                                r = client.get(url)
                                if r.status_code == 200 and len(r.content) > 1000:
                                    cale_pdf = f"temp_{nume_pdf}"
                                    with open(cale_pdf, "wb") as f_pdf:
                                        f_pdf.write(r.content)
                                    media = MediaFileUpload(cale_pdf, mimetype="application/pdf")
                                    metadata = {'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]}
                                    service.files().create(body=metadata, media_body=media, supportsAllDrives=True).execute()
                                    os.remove(cale_pdf)
                                    row[col] = "20"
                                    modificari = True
                                    print(f"   ✅ Salvat sufix: {nume_pdf}")
                                    continue
                                else:
                                    stare_noua = stare_curenta + 1
                                    row[col] = str(stare_noua)
                                    modificari = True
                                    print(f"   ❌ Sufix inexistent pe server. Stare nouă pentru {col.upper()}: {stare_noua}")
                                    
                                    # La a doua ratare (starea devine 2), declarăm inexistent și propagăm în cascadă la 10
                                    if stare_noua == 2:
                                        print(f"   ⚠️ Propagare inexistență pentru restul sufixelor de la {sufix_url} în sus...")
                                        for i_rest in range(idx, len(config_sufixe)):
                                            row[config_sufixe[i_rest]["col"]] = "10"
                                        break
                                time.sleep(random.uniform(0.1, 0.2))
                            except Exception as e:
                                print(f"   ❌ Eroare rețea la sufix {nume_pdf}: {e}")
                                time.sleep(1.0)
                                break
            if modificari:
                salveaza_csv_in_drive(service, file_id, nume_csv, list(rows_dict.values()))
            else:
                print(f"ℹ️ Fără modificări pe sufixe pentru anul {an}.")

if __name__ == "__main__":
    descarca_sufixe()
