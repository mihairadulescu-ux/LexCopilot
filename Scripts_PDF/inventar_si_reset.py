import os
import sys
import json
import csv
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Configurații globale din mediu
TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")
MIN_SIZE_BYTES = 1000  # Pragul sub care considerăm PDF-ul ca fiind corupt/dummy eroare

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def listeaza_si_curata_pdf_uri(service, drive_folder_pdf):
    print(f"📂 Scanare profundă și validare integritate folder PDF (ID: {drive_folder_pdf})...", flush=True)
    pdf_uri = []
    page_token = None
    
    # Am scos filtrul rigid de mimeType pentru a asigura că indexăm corect și nu omitem nimic la scanare
    query = f"'{drive_folder_pdf}' in parents and trashed = false"
    
    while True:
        try:
            response = service.files().list(
                q=query, 
                spaces='drive',
                fields="nextPageToken, files(id, name, size)", 
                pageToken=page_token, 
                pageSize=1000,
                supportsAllDrives=True, 
                includeItemsFromAllDrives=True, 
                corpora="allDrives"  # CRUCIAL pentru Shared Drives: caută nativ în toată structura drive-ului mapat
            ).execute()
            
            files = response.get("files", [])
            
            for file in files:
                name = file.get("name", "")
                
                # Ignorăm fișierele CSV de status existente din folder ca să nu le procesăm ca fiind PDF-uri corupte
                if name.startswith("status_") and name.endswith(".csv"):
                    continue
                    
                file_id = file.get("id")
                size = int(file.get("size", 0))
                
                # --- VERIFICARE ȘI ELIMINARE FANTOME (DUMMY) ---
                if size < MIN_SIZE_BYTES:
                    print(f"🗑️ [CURĂȚARE] Placeholder/Fișier invalid detectat și eliminat: {name} ({size} bytes).", flush=True)
                    try:
                        service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
                    except Exception as e:
                        print(f"⚠️ Eroare la ștergerea fișierului {name}: {e}", flush=True)
                else:
                    if name.lower().endswith('.pdf'):
                        pdf_uri.append(file)
                        
            page_token = response.get("nextPageToken", None)
            if not page_token:
                break
        except Exception as e:
            print(f"❌ Eroare critică în timpul listării fișierelor din Drive: {e}", flush=True)
            break
            
    print(f"📊 Scanare completă. S-au păstrat {len(pdf_uri)} fișiere PDF reale și valide în stocarea Cloud.", flush=True)
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
        print("❌ EROARE CRITICĂ: Variabila DRIVE_FOLDER_PDF nu este setată în mediu.")
        sys.exit(1)

    service = obtine_drive()
    toate_pdf_urile = listeaza_si_curata_pdf_uri(service, TARGET_FOLDER_ID)
    
    structura_ani = {}
    for pdf in toate_pdf_urile:
        an, nr_baza, sufix = sparge_numar_si_sufix(pdf["name"])
        if an and nr_baza:
            if an not in structura_ani: structura_ani[an] = {}
            if nr_baza not in structura_ani[an]: structura_ani[an][nr_baza] = {}
            structura_ani[an][nr_baza][sufix] = {"id": pdf["id"], "size_kb": round(int(pdf.get("size", 0))/1024, 1)}

    print(f"\n💾 Generare registre CSV de control direct în folderul destinație...", flush=True)
    for an, numere_baza in sorted(structura_ani.items()):
        nume_registru = f"status_{an}.csv"
        
        # Securizăm limita maximă de scanare per an
        maxim_nr_baza = min(max(numere_baza.keys()), 1350)
        
        randuri_csv = []
        for nr in range(1, maxim_nr_baza + 1):
            if nr in numere_baza:
                sub_editii = numere_baza[nr]
                
                # Înregistrăm numărul de bază/simplu
                if "" in sub_editii:
                    randuri_csv.append([str(nr), "", "descarcat", sub_editii[""]["size_kb"], sub_editii[""]["id"]])
                else:
                    randuri_csv.append([str(nr), "", "", "0", ""])
                    
                # Înregistrăm sufixele ierarhice (Bis, Tris, etc.) ordonate corect matematic
                sufixe_ordonate = sorted([s for s in sub_editii.keys() if s != ""], key=cheie_sortare_sufixe)
                for sufix in sufixe_ordonate:
                    randuri_csv.append([str(nr), sufix, "descarcat", sub_editii[sufix]["size_kb"], sub_editii[sufix]["id"]])
            else:
                # Dacă numărul lipsește complet, completăm linia de bază liberă
                randuri_csv.append([str(nr), "", "", "0", ""])

        # Scrierea fizică a CSV-ului temporar
        cale_temp = f"temp_{nume_registru}"
        with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"])
            writer.writerows(randuri_csv)
                
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        
        # Interogăm Drive-ul pentru a face update direct sau creare curată
        query_reg = f"'{TARGET_FOLDER_ID}' in parents and name = '{nume_registru}' and trashed = false"
        existente = service.files().list(
            q=query_reg, 
            fields="files(id)", 
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="allDrives"
        ).execute().get("files", [])
        
        if existente:
            service.files().update(fileId=existente[0]["id"], media_body=media, supportsAllDrives=True).execute()
        else:
            service.files().create(body={'name': nume_registru, 'parents': [TARGET_FOLDER_ID]}, media_body=media, fields="id", supportsAllDrives=True).execute()
            
        if os.path.exists(cale_temp):
            os.remove(cale_temp)
            
        print(f"    ✅ Registrul istoric [{nume_registru}] a fost sincronizat cu succes în cloud.", flush=True)

if __name__ == "__main__":
    reseteaza_tot()
