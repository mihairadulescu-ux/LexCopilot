import os
import sys
import json
import time
import random
import csv
import io
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

ORIGIN_FOLDER_ID = "1c8SEo8UrQVe6qgzPFGLXJFiMyLeI-r8D"  # Sursa veche (Personal Drive)
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")        # Destinația nouă (Shared Drive)

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def descarca_csv_din_drive(service, file_id):
    """Descarcă un fișier CSV direct din Drive în memorie."""
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        from googleapiclient.http import MediaIoBaseDownload
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue().decode("utf-8").splitlines()
    except Exception as e:
        print(f"❌ Eroare la descărcarea registrului (ID: {file_id}): {e}")
        return []

def copiaza_valide():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE CRITICĂ: DRIVE_FOLDER_PDF nu este setat în GitHub Variables!")
        sys.exit(1)

    print("🚀 Începe copierea selectivă ultra-rapidă...")
    service = obtine_drive()

    # ------------------------------------------------------------------
    # PASUL 1: Mapăm toate fișierele din folderul sursă vechi (Personal Drive)
    # ------------------------------------------------------------------
    print("📂 Pasul 1: Mapare ID-uri fișiere brute din folderul sursă vechi...", flush=True)
    fisiere_sursa = {}
    page_token = None
    query_sursa = f"'{ORIGIN_FOLDER_ID}' in parents and trashed = false"
    
    while True:
        response = service.files().list(
            q=query_sursa,
            fields="nextPageToken, files(id, name, size)",
            pageToken=page_token,
            pageSize=1000,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="user"
        ).execute()
        
        for f in response.get("files", []):
            fisiere_sursa[f["name"]] = {"id": f["id"], "size": int(f.get("size", 0))}
            
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    print(f"   ↳ Mapare finalizată. Detectat un total de {len(fisiere_sursa)} fișiere fizice în sursa veche.", flush=True)

    # ------------------------------------------------------------------
    # PASUL 2: Identificăm registrele CSV din noul Shared Drive
    # ------------------------------------------------------------------
    print("\n📊 Pasul 2: Identificare registre status_YYYY.csv din noul Shared Drive...", flush=True)
    registre_id = {}
    page_token = None
    query_target = f"'{TARGET_FOLDER_ID}' in parents and name contains 'status_' and name contains '.csv' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query_target,
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
            pageSize=100,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="drive",
            driveId=TARGET_FOLDER_ID
        ).execute()
        
        for f in response.get("files", []):
            registre_id[f["name"]] = f["id"]
            
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    print(f"   ↳ Identificate {len(registre_id)} registre de stare CSV în destinație.", flush=True)

    if not registre_id:
        print("❌ EROARE: Nu am găsit niciun registru status_YYYY.csv în Shared Drive-ul destinație!")
        sys.exit(1)

    # ------------------------------------------------------------------
    # PASUL 3: Mapăm ce fișiere sunt deja în Shared Drive pentru a nu le duplica
    # ------------------------------------------------------------------
    print("\n📂 Pasul 3: Mapare fișiere PDF deja copiate în noul Shared Drive...", flush=True)
    fisiere_destinatie_existente = set()
    page_token = None
    query_dest = f"'{TARGET_FOLDER_ID}' in parents and name contains 'MO_PI_' and name contains '.pdf' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query_dest,
            fields="nextPageToken, files(name)",
            pageToken=page_token,
            pageSize=1000,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="drive",
            driveId=TARGET_FOLDER_ID
        ).execute()
        
        for f in response.get("files", []):
            fisiere_destinatie_existente.add(f["name"])
            
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    print(f"   ↳ Am detectat {len(fisiere_destinatie_existente)} fișiere PDF deja sosite în noul Shared Drive.", flush=True)

    # ------------------------------------------------------------------
    # PASUL 4: Copierea selectivă bazată strictly pe starea din CSV (status == 20)
    # ------------------------------------------------------------------
    print("\n⚙️ Pasul 4: Începem procesarea registrelor pentru copiere...", flush=True)
    total_copiate_acum = 0
    
    # Sortăm registrele după an ca să lucrăm organizat (status_2000.csv -> status_2026.csv)
    for nume_csv, csv_id in sorted(registre_id.items()):
        # Extragem anul din numele CSV-ului
        an = nume_csv.split("_")[1].split(".")[0]
        print(f"\n📂 Procesăm registrul pentru anul {an} ({nume_csv})...", flush=True)
        
        linii_csv = descarca_csv_din_drive(service, csv_id)
        if not linii_csv:
            continue
            
        reader = csv.DictReader(linii_csv)
        
        for row in reader:
            numar = row["numar"]
            
            # Mapăm fiecare ediție posibilă definită în coloane
            editii = {
                "simplu": "",
                "bis": "Bis",
                "tris": "Tris",
                "quatro": "Quatro",
                "s": "S"
            }
            
            for coloana, sufix in editii.items():
                stare = int(row.get(coloana, 0))
                
                # Regula de Aur: Copiem DOAR dacă starea din registru este 20 (OK / Validă)
                if stare == 20:
                    nume_pdf = f"MO_PI_{an}_{numar}{sufix}.pdf"
                    
                    # 1. Verificăm dacă fișierul este deja copiat în destinație
                    if nume_pdf in fisiere_destinatie_existente:
                        continue
                        
                    # 2. Verificăm dacă fișierul există fizic în sursa veche
                    if nume_pdf not in fisiere_sursa:
                        print(f"⚠️ Atenție: Registrul indică stare 20 pentru {nume_pdf}, dar fișierul lipsește din sursa veche!")
                        continue
                        
                    info_sursa = fisiere_sursa[nume_pdf]
                    
                    # 3. Executăm copierea server-to-server nativă
                    try:
                        copie_metadata = {
                            'name': nume_pdf,
                            'parents': [TARGET_FOLDER_ID]
                        }
                        
                        service.files().copy(
                            fileId=info_sursa["id"],
                            body=copie_metadata,
                            supportsAllDrives=True
                        ).execute()
                        
                        total_copiate_acum += 1
                        print(f"   📥 [OK] Copiat cu succes: {nume_pdf}", flush=True)
                        
                        # Adăugăm în lista temporară locală pentru a preveni încercările multiple la aceeași rulare
                        fisiere_destinatie_existente.add(nume_pdf)
                        
                        # Scurtă pauză pentru controlul rate-limiting-ului API
                        time.sleep(random.uniform(0.15, 0.35))
                        
                    except Exception as e:
                        print(f"   ❌ Eroare la copierea {nume_pdf}: {e}", flush=True)

    print(f"\n🎉 OPERAȚIUNE FINALIZATĂ!")
    print(f"📊 S-au copiat selectiv în noul Shared Drive un total de: {total_copiate_acum} PDF-uri valide.")
    print("🧹 Fișierele dummy de 1 byte au fost lăsate în urmă în siguranță.")

if __name__ == "__main__":
    copiaza_valide()
