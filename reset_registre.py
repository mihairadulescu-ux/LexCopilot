import os
import sys
import json
import csv
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Configurații
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")
MIN_SIZE_BYTES = 1000  # Pragul sub care considerăm PDF-ul ca fiind corupt/eroare

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_si_curata_pdf_uri(service, drive_folder_pdf):
    print(f"📂 Scanare și validare integritate folder PDF (ID: {drive_folder_pdf})...")
    pdf_uri = []
    page_token = None
    query = f"'{drive_folder_pdf}' in parents and mimeType = 'application/pdf' and trashed = false"
    
    while True:
        response = service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name, size)", 
            pageToken=page_token, 
            pageSize=1000,
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True, 
            corporas="user"
        ).execute()
        
        files = response.get("files", [])
        
        for file in files:
            file_id = file.get("id")
            name = file.get("name")
            size = int(file.get("size", 0))
            
            # --- VERIFICARE INTEGRITATE ---
            if size < MIN_SIZE_BYTES:
                print(f"⚠️ [CURĂȚARE] Fișier corupt/incomplet detectat: {name} ({size} bytes). Ștergere...")
                service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            else:
                pdf_uri.append(file)
                
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    print(f"📊 S-au păstrat {len(pdf_uri)} fișiere PDF valide în Drive.")
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
    ordine = {"Bis": 1, "Tris": 2, "Quater": 3, "S": 4, "Supliment": 5}
    return ordine.get(sufix, 100), sufix

def reseteaza_tot():
    if not TARGET_FOLDER_ID:
        print("❌ EROARE: DRIVE_FOLDER_PDF nu este setată.")
        sys.exit(1)

    service = obtine_drive()
    toate_pdf_urile = listeaza_si_curata_pdf_uri(service, TARGET_FOLDER_ID)
    
    structura_ani = {}
    for pdf in toate_pdf_urile:
        an, nr_baza, sufix = sparge_numar_si_sufix(pdf["name"])
        if an and nr_baza:
            if an not in structura_ani: structura_ani[an] = {}
            if nr_baza not in structura_ani[an]: structura_ani[an][nr_baza] = {}
            structura_ani[an][nr_baza][sufix] = {"id": pdf["id"], "size_kb": round(int(pdf["size"])/1024, 1)}

    for an, numere_baza in sorted(structura_ani.items()):
        nume_registru = f"status_{an}.csv"
        maxim_nr_baza = min(max(numere_baza.keys()), 1200)
        
        randuri_csv = []
        for nr in range(1, maxim_nr_baza + 1):
            if nr in numere_baza:
                sub_editii = numere_baza[nr]
                # Număr principal
                if "" in sub_editii:
                    randuri_csv.append([str(nr), "", "descarcat", sub_editii[""]["size_kb"], sub_editii[""]["id"]])
                else:
                    randuri_csv.append([str(nr), "", "", "0", ""])
                # Sufixe
                sufixe_ordonate = sorted([s for s in sub_editii.keys() if s != ""], key=cheie_sortare_sufixe)
                for sufix in sufixe_ordonate:
                    randuri_csv.append([str(nr), sufix, "descarcat", sub_editii[sufix]["size_kb"], sub_editii[sufix]["id"]])
            else:
                randuri_csv.append([str(nr), "", "", "0", ""])

        # Suprascriere registru
        cale_temp = f"temp_{nume_registru}"
        with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
            writer.writerows(randuri_csv)
                
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        # Căutăm registrul existent ca să-i dăm update, sau creăm unul nou
        query_reg = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
        existente = service.files().list(q=query_reg, fields="files(id)", supportsAllDrives=True).execute().get("files", [])
        
        if existente:
            service.files().update(fileId=existente[0]["id"], media_body=media, supportsAllDrives=True).execute()
        else:
            service.files().create(body={'name': nume_registru, 'parents': [TARGET_FOLDER_ID]}, media_body=media, fields="id", supportsAllDrives=True).execute()
        os.remove(cale_temp)
        print(f"    ✅ Registru {nume_registru} actualizat.")

if __name__ == "__main__":
    reseteaza_tot()
