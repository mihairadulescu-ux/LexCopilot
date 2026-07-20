import os
import sys
import csv
import json
import re
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

CALE_INDEX_LOCAL = "index_xml.json"

def get_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    github_secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if github_secret:
        service_account_info = json.loads(github_secret)
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        credentials_path = "service_account.json"
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Nu s-a găsit fișierul '{credentials_path}'!")
        creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
        
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def extrage_taguri_din_matrice(service, ani_procesare):
    if not os.path.exists(CALE_INDEX_LOCAL):
        print(f"{ROSU}🛑 Eroare Extragere: Nu s-a găsit fișierul '{CALE_INDEX_LOCAL}'!{RESET}")
        sys.exit(1)

    with open(CALE_INDEX_LOCAL, "r", encoding="utf-8") as f:
        data_master = json.load(f)

    fisiere_map = data_master.get("fisiere", {})

    emitenti_gasiti = set()
    tipuri_acte_gasite = set()

    # Regex mai permisiv pentru tag-uri cu atribute sau namespace-uri
    regex_emitent = re.compile(r"<[^>]*?Emitent[^>]*?>(.*?)</[^>]*?Emitent>", re.DOTALL | re.IGNORECASE)
    regex_tip_act = re.compile(r"<[^>]*?TipAct[^>]*?>(.*?)</[^>]*?TipAct>", re.DOTALL | re.IGNORECASE)

    # Filtram fișierele din index care aparțin anilor ceruți
    fisiere_tinta = [
        (nume, info) for nume, info in fisiere_map.items() 
        if info.get('an') in ani_procesare
    ]

    string_ani = "_".join([str(a) for a in ani_procesare])
    print(f"\n{GALBEN}⚡ [Dictionare] Scanare pe index pentru anii {string_ani} ({len(fisiere_tinta)} fișiere selectate)...{RESET}", flush=True)

    contor_total_procesat = 0

    for nume_fisier, info in fisiere_tinta:
        file_id = info.get('id')
        if not file_id:
            continue

        try:
            cerere = service.files().get_media(fileId=file_id, supportsAllDrives=True)
            fh = io.BytesIO()
            descarcare = MediaIoBaseDownload(fh, cerere)
            gata = False
            while not gata:
                _, gata = descarcare.next_chunk()
            
            xml_text = fh.getvalue().decode("utf-8", errors="ignore")
            
            for em in regex_emitent.findall(xml_text):
                val = em.strip()
                if val: 
                    emitenti_gasiti.add(val)
                
            for ta in regex_tip_act.findall(xml_text):
                val = ta.strip()
                if val: 
                    tipuri_acte_gasite.add(val)

            contor_total_procesat += 1

            if contor_total_procesat % 100 == 0:
                print(f"   📊 [Progres] Procesate: {contor_total_procesat}/{len(fisiere_tinta)} fișiere", flush=True)

        except Exception as e:
            print(f"⚠️ Eroare la fișierul {nume_fisier}: {e}", flush=True)
            continue

    print(f"\n✅ [Procesare Finalizată] Total fișiere scanate: {contor_total_procesat}", flush=True)

    cale_emitenti = f"lista_emitenti_{string_ani}.csv"
    cale_acte = f"lista_tip_acte_{string_ani}.csv"
    
    with open(cale_emitenti, mode='w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['Emitent'])
        for e in sorted(list(emitenti_gasiti)):
            writer.writerow([e])
            
    with open(cale_acte, mode='w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['Tip_Act'])
        for t in sorted(list(tipuri_acte_gasite)):
            writer.writerow([t])
            
    print(f"{VERDE}✅ [Gata] Lista brute de emitenți și tipuri de acte salvată în '{cale_emitenti}' și '{cale_acte}'!{RESET}", flush=True)

if __name__ == "__main__":
    argumente_numerice = []
    for arg in sys.argv[1:]:
        piese = arg.split()
        for piesa in piese:
            if piesa.isdigit():
                argumente_numerice.append(int(piesa))

    if len(argumente_numerice) == 1:
        ani_finali = [argumente_numerice[0]]
    elif len(argumente_numerice) >= 2:
        ani_finali = list(range(argumente_numerice[0], argumente_numerice[1] + 1))
    else:
        print(f"{ROSU}🛑 Eroare: Lipsesc anii ca parametru! (Exemplu: python script.py 2020 2024){RESET}")
        sys.exit(1)
        
    drive_service = get_drive_service()
    extrage_taguri_din_matrice(drive_service, ani_finali)
