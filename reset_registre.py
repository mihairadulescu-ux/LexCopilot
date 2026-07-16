import os
import sys
import json
import csv
import io
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF", "1gRh-rWe32RNJU2PmN67XoFvkaCSotTA1")
# Resetăm toți anii din intervalul de producție
YEARS_TO_RESET = list(range(2000, 2027)) 

def obtine_drive():
    print("🔑 [Reset] Conectare Google Drive...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_fisiere_fizice_an(service, an):
    print(f"📂 Scanare fișiere existente în Drive pentru anul {an}...")
    fisiere_fizice = set()
    page_token = None
    query = f"'{TARGET_FOLDER_ID}' in parents and name contains 'MO_PI_{an}_' and name contains '.pdf' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query, fields="nextPageToken, files(name)", pageToken=page_token, pageSize=1000,
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
        ).execute()
        for f in response.get("files", []):
            # Eliminăm extensia .pdf pentru o mapare ușoară în memorie (ex: MO_PI_2024_12Bis)
            fisiere_fizice.add(f["name"].replace(".pdf", ""))
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
    print(f"📊 S-au găsit {len(fisiere_fizice)} PDF-uri reale în Drive pentru anul {an}.")
    return fisiere_fizice

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
        return file_id, list(csv.DictReader(linii))
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
    cale_temp = f"temp_reset_{nume_csv}"
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["numar", "simplu", "bis", "tris", "quatro", "s"])
        writer.writeheader()
        writer.writerows(date_rows)
    media = MediaFileUpload(cale_temp, mimetype="text/csv")
    service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
    os.remove(cale_temp)

def reseteaza_tot():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE: DRIVE_FOLDER_PDF nu este setat!")
        sys.exit(1)
    service = obtine_drive()
    
    for an in YEARS_TO_RESET:
        print(f"\n⚙️ Re-aliniere registre pentru anul {an}...")
        fisiere_existente = listeaza_fisiere_fizice_an(service, an)
        file_id, rows = obtine_sau_creaza_csv(service, an)
        
        for r in rows:
            numar = r["numar"]
            
            # 1. Aliniere număr simplu
            nume_simplu = f"MO_PI_{an}_{numar}"
            if nume_simplu in fisiere_existente:
                r["simplu"] = "20"
            else:
                r["simplu"] = "0" # Resetăm contorul pentru reîncercare curată
                
            # 2. Aliniere sufixe
            for col, sufix_url in [("bis", "Bis"), ("tris", "Tris"), ("quatro", "Quatro"), ("s", "S")]:
                nume_sufix = f"MO_PI_{an}_{numar}{sufix_url}"
                if nume_sufix in fisiere_existente:
                    r[col] = "20"
                else:
                    # Dacă simplu nu există, sufixele sunt marcate automat ca inexistente (10)
                    if r["simplu"] == "0":
                        r[col] = "10"
                    else:
                        r[col] = "0" # Resetăm pentru reîncercare
                        
        salveaza_csv_in_drive(service, file_id, f"status_{an}.csv", rows)
        print(f"✅ Registru resetat și curățat conform realității din Drive pentru anul {an}!")

if __name__ == "__main__":
    reseteaza_tot()
