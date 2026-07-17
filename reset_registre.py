import os
import sys
import json
import csv
import io
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Destinația pentru folderele de PDF brute (Citesște din aceleași Variabile)
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")

def obtine_drive():
    print("🔑 [Reset] Conectare Google Drive...")
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipsește secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_toate_pdf_urile_fizice(service):
    print(f"📂 Scanare generală folder PDF (ID: {TARGET_FOLDER_ID})...")
    pdf_uri = []
    page_token = None
    query = f"'{TARGET_FOLDER_ID}' in parents and mimeType = 'application/pdf' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name, size)", 
            pageToken=page_token, 
            pageSize=1000,
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True, 
            corpora="user"
        ).execute()
        
        pdf_uri.extend(response.get("files", []))
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    print(f"📊 S-au găsit în total {len(pdf_uri)} fișiere PDF fizice în Drive.")
    return pdf_uri

def sparge_numar_si_sufix(nume_fisier):
    m = re.search(r"MO_PI_(\d{4})_([A-Za-z0-9]+)\.pdf", nume_fisier)
    if m:
        an = m.group(1)
        numar_complet = m.group(2)
        
        match_baza = re.match(r"^(\d+)", numar_complet)
        if match_baza:
            nr_baza = int(match_baza.group(1))
            sufix = numar_complet[len(match_baza.group(1)):]
            return an, nr_baza, sufix
            
    return None, None, None

def cheie_sortare_sufixe(sufix):
    """Ordonează sufixele ierarhic conform legilor de publicare."""
    ordine = {"Bis": 1, "Tris": 2, "Quater": 3, "S": 4, "Supliment": 5}
    # Dacă e un sufix exotic nestandardizat, îl punem la final ordonat alfabetic
    return ordine.get(sufix, 100), sufix

def reseteaza_tot():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE CRITICĂ: Variabila DRIVE_FOLDER_PDF este goală în mediu!")
        sys.exit(1)

    service = obtine_drive()
    toate_pdf_urile = listeaza_toate_pdf_urile_fizice(service)
    
    if not toate_pdf_urile:
        print("⚠️ ATENȚIE: Nu s-a găsit niciun PDF potrivit în folder! Nimic de resetat.")
        return

    structura_ani = {}
    
    for pdf in toate_pdf_urile:
        nume = pdf["name"]
        an, nr_baza, sufix = sparge_numar_si_sufix(nume)
        
        if an and nr_baza:
            if an not in structura_ani:
                structura_ani[an] = {}
            if nr_baza not in structura_ani[an]:
                structura_ani[an][nr_baza] = {}
                
            raw_size = pdf.get("size")
            size_kb = round(int(raw_size) / 1024, 1) if raw_size else 0.0
            
            structura_ani[an][nr_baza][sufix] = {
                "id": pdf["id"],
                "size_kb": size_kb
            }

    print(f"🗂️ Fișierele au fost catalogate structural pentru {len(structura_ani)} ani.")

    for an, numere_baza in sorted(structura_ani.items()):
        nume_registru = f"status_{an}.csv"
        
        maxim_nr_baza = max(numere_baza.keys())
        print(f"⚙️ Generare registru structural: {nume_registru} (Număr maxim detectat: {maxim_nr_baza})...")
        
        randuri_csv = []
        
        for nr in range(1, maxim_nr_baza + 1):
            if nr in numere_baza:
                sub_editii = numere_baza[nr]
                
                # 1. Mapăm numărul principal de bază
                if "" in sub_editii:
                    randuri_csv.append([str(nr), "", "descarcat", sub_editii[""]["size_kb"], sub_editii[""]["id"]])
                else:
                    # Găură pe numărul principal (dar avem un S sau un Bis independent în Drive)
                    randuri_csv.append([str(nr), "", "", "0", ""])
                
                # 2. Mapăm edițiile speciale ordonate ierarhic (Bis -> Tris -> Quater -> S)
                sufixe_ordonate = sorted([s for s in sub_editii.keys() if s != ""], key=cheie_sortare_sufixe)
                for sufix in sufixe_ordonate:
                    randuri_csv.append([str(nr), sufix, "descarcat", sub_editii[sufix]["size_kb"], sub_editii[sufix]["id"]])
            else:
                # Găură completă pe numărul principal -> status gol pentru a fi prins la download
                randuri_csv.append([str(nr), "", "", "0", ""])

        # Identificare și suprascriere în Drive direct în folderul principal
        query_reg = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
        existente = service.files().list(
            q=query_reg, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
        ).execute().get("files", [])
        
        cale_temp = f"temp_{nume_registru}"
        with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
            writer.writerows(randuri_csv)
                
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        if existente:
            file_id = existente[0]["id"]
            service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            print(f"    💾 Sincronizat [UPDATE STRUCTURAL]: {nume_registru} (ID: {file_id})")
        else:
            metadata = {'name': nume_registru, 'parents': [TARGET_FOLDER_ID]}
            nou = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
            print(f"    🆕 Generat [CREATE STRUCTURAL]: {nume_registru} (ID: {nou['id']})")
            
        os.remove(cale_temp)
        
    print("🚀 Sincronizarea registrelor structurale s-a terminat! Toate găurile sunt aliniate ierarhic.")

if __name__ == "__main__":
    reseteaza_tot()
