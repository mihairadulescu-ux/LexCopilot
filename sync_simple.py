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
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

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
    print(f"💾 Registru actualizat cu succes: {nume_csv}")

def descarca_monitoare():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE: DRIVE_FOLDER_PDF nu este setat!")
        sys.exit(1)
    service = obtine_drive()
    
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for an in YEARS_TO_PROCESS:
            print(f"\n--- 📅 Sincronizare numere simple Anul {an} ---")
            nume_csv = f"status_{an}.csv"
            file_id, rows = obtine_sau_creaza_csv(service, an)
            modificari = False
            rows_dict = {int(r["numar"]): r for r in rows}
            
            # Găsim ultimul număr cu adevărat procesat din istoric
            ultimul_numar_procesat = 0
            for n in range(1500, 0, -1):
                if int(rows_dict[n]["simplu"]) in [10, 15, 20]:
                    ultimul_numar_procesat = n
                    break
            
            # Pentru anul curent, limităm interogarea la cel mult 10 numere peste ultimul monitor valid cunoscut.
            # Pentru anii trecuți, limita este strict ultimul număr din registru.
            if an == AN_CURENT:
                limita_maxima_interogare = min(1500, max(1, ultimul_numar_procesat) + 10)
                print(f"📊 [An curent] Ultimul cunoscut: {ultimul_numar_procesat}. Căutăm monitoare noi în zona: 1 ➔ {limita_maxima_interogare}")
            else:
                limita_maxima_interogare = ultimul_numar_procesat
                print(f"📊 [An istoric] Scanare fixă pe zona existentă: 1 ➔ {limita_maxima_interogare}")
            
            eroare_consecutiva_404 = 0
            
            for numar in range(1, limita_maxima_interogare + 1):
                if eroare_consecutiva_404 >= 15:
                    print(f"🛑 Oprim scanarea pe anul {an}: s-a atins granița publicațiilor noi.")
                    break
                    
                row = rows_dict[numar]
                stare_simpla = int(row["simplu"])
                
                if stare_simpla in [15, 20]:
                    eroare_consecutiva_404 = 0
                    continue
                if stare_simpla == 10:
                    # Propagăm automat starea inexistentă
                    for col in ["bis", "tris", "quatro", "s"]:
                        if row[col] != "10":
                            row[col] = "10"
                            modificari = True
                    continue
                
                if 0 <= stare_simpla <= 4:
                    url = URL_TEMPLATE.format(an=an, numar=numar)
                    nume_pdf = f"MO_PI_{an}_{numar}.pdf"
                    try:
                        print(f"🔍 Descărcare {nume_pdf} (Încercarea {stare_simpla})...")
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
                            print(f"   ✅ Salvat în Drive: {nume_pdf}")
                        else:
                            stare_noua = stare_simpla + 1
                            row["simplu"] = str(stare_noua)
                            modificari = True
                            
                            # Incrementare contor erori consecutive garantată pentru orice tip de eșec sau redirecționare
                            eroare_consecutiva_404 += 1
                            print(f"   ⚠️ Eșec (HTTP {r.status_code}). Stare nouă pentru {nume_pdf}: {stare_noua}")
                            
                            if stare_noua == 5:
                                row["simplu"] = "15"
                                for col in ["bis", "tris", "quatro", "s"]:
                                    row[col] = "10"
                                nume_failed = f"MO_PI_{an}_{numar}_FAILED.pdf"
                                cale_failed = f"temp_{nume_failed}"
                                with open(cale_failed, "w") as f_failed:
                                    f_failed.write(url)
                                media = MediaFileUpload(cale_failed, mimetype="text/plain")
                                metadata = {'name': nume_failed, 'parents': [TARGET_FOLDER_ID]}
                                service.files().create(body=metadata, media_body=media, supportsAllDrives=True).execute()
                                os.remove(cale_failed)
                                print(f"   🛑 Promovat la 15 (FAILED): {nume_failed}")
                        time.sleep(random.uniform(0.1, 0.3))
                    except Exception as e:
                        print(f"   ❌ Eroare rețea/conexiune la {nume_pdf}: {e}")
                        row["simplu"] = str(stare_simpla + 1)
                        modificari = True
                        eroare_consecutiva_404 += 1  # Incrementăm și pe problemele de conexiune fizică
                        time.sleep(2.0)
            if modificari:
                salveaza_csv_in_drive(service, file_id, nume_csv, list(rows_dict.values()))
            else:
                print(f"ℹ️ Fără modificări pentru anul {an}.")

if __name__ == "__main__":
    descarca_monitoare()
