import os
import sys
import json
import csv
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_si_curata_pdf_uri(service, drive_folder_pdf, an):
    print(f"📂 Scanare profundă și validare structurală Cloud pentru anul {an}...", flush=True)
    pdf_uri = []
    page_token = None
    
    # Filtrăm query-ul direct la nivel de API ca să aducă DOAR fișierele anului respectiv!
    query = f"'{drive_folder_pdf}' in parents and name contains 'MO_PI_{an}_' and trashed = false"
    
    while True:
        try:
            response = service.files().list(
                q=query, spaces='drive', fields="nextPageToken, files(id, name, size, mimeType)", 
                pageToken=page_token, pageSize=1000, supportsAllDrives=True, 
                includeItemsFromAllDrives=True, corpora="allDrives"
            ).execute()
            
            for file in response.get("files", []):
                name = file.get("name", "")
                if name.startswith("status_") and name.endswith(".csv"):
                    continue
                    
                file_id = file.get("id")
                mime_type = file.get("mimeType", "")
                size = int(file.get("size", 0))
                
                if name.lower().endswith('.pdf') and mime_type != 'application/pdf':
                    print(f"🗑️ Ștergere fișier dummy/invalid detectat: {name}", flush=True)
                    try:
                        service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
                    except:
                        pass
                elif name.lower().endswith('.pdf') and mime_type == 'application/pdf':
                    pdf_uri.append(file)
                        
            page_token = response.get("nextPageToken", None)
            if not page_token:
                break
        except Exception as e:
            print(f"{ROSU}❌ Eroare scanare: {e}{RESET}", flush=True)
            break
            
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

def reseteaza_an_specific(an):
    if not TARGET_FOLDER_ID:
        print(f"{ROSU}❌ Variabila DRIVE_FOLDER_PDF lipseste.{RESET}")
        sys.exit(1)

    service = obtine_drive()
    toate_pdf_urile = listeaza_si_curata_pdf_uri(service, TARGET_FOLDER_ID, an)
    
    numere_baza = {}
    for pdf in toate_pdf_urile:
        _, nr_baza, sufix = sparge_numar_si_sufix(pdf["name"])
        if nr_baza:
            if nr_baza not in numere_baza: numere_baza[nr_baza] = {}
            numere_baza[nr_baza][sufix] = {"id": pdf["id"], "size_kb": round(int(pdf.get("size", 0))/1024, 1)}

    nume_registru = f"status_{an}.csv"
    print(f"💾 Reconstructie registru unificat local [{nume_registru}]...", flush=True)
    
    maxim_nr_baza = min(max(numere_baza.keys()) if numere_baza else 1, 1350)
    if maxim_nr_baza < 1: maxim_nr_baza = 1
    
    randuri_csv = []
    for nr in range(1, maxim_nr_baza + 1):
        if nr in numere_baza:
            sub_editii = numere_baza[nr]
            if "" in sub_editii:
                randuri_csv.append([str(nr), "", "descarcat", sub_editii[""]["size_kb"], sub_editii[""]["id"]])
            else:
                randuri_csv.append([str(nr), "", "", "0", ""])
                
            sufixe_ordonate = sorted([s for s in sub_editii.keys() if s != ""], key=cheie_sortare_sufixe)
            for sufix in sufixe_ordonate:
                randuri_csv.append([str(nr), sufix, "descarcat", sub_editii[sufix]["size_kb"], sub_editii[sufix]["id"]])
        else:
            randuri_csv.append([str(nr), "", "", "0", ""])

    cale_temp = f"temp_{nume_registru}"
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow(["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
        writer.writerows(randuri_csv)
            
    media = MediaFileUpload(cale_temp, mimetype="text/csv")
    query_reg = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
    existente = service.files().list(q=query_reg, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives").execute().get("files", [])
    
    if existente:
        service.files().update(fileId=existente[0]["id"], media_body=media, supportsAllDrives=True).execute()
    else:
        service.files().create(body={'name': nume_registru, 'parents': [TARGET_FOLDER_ID]}, media_body=media, supportsAllDrives=True).execute()
        
    if os.path.exists(cale_temp):
        os.remove(cale_temp)
    print(f"    ✅ Registrul [{nume_registru}] a fost sincronizat cu succes in cloud.", flush=True)

if __name__ == "__main__":
    an_tinta = sys.argv[1] if len(sys.argv) > 1 else os.getenv("AN_TINTA", "2000")
    print(f"🎯 [RESET] Pornire operatiune pentru anul: {an_tinta}")
    reseteaza_an_specific(int(an_tinta))
