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
    if not os.path.exists("index_fisiere.json"):
        print(f"{ROSU}🛑 Eroare Extragere: Nu s-a găsit fișierul 'index_fisiere.json'!{RESET}")
        sys.exit(1)

    with open("index_fisiere.json", "r", encoding="utf-8") as f:
        index_data = json.load(f)

    emitenti_gasiti = set()
    tipuri_acte_gasite = set()

    regex_emitent = re.compile(r"<[^:>]*:?Emitent>(.*?)</[^:>]*:?Emitent>", re.DOTALL)
    regex_tip_act = re.compile(r"<[^:>]*:?TipAct>(.*?)</[^:>]*:?TipAct>", re.DOTALL)

    for target_year in ani_procesare:
        fisiere_an = index_data.get(str(target_year), [])
        print(f"\n{GALBEN}⚡ [Dictionare] Scanare rapidă pe index pentru anul {target_year} ({len(fisiere_an)} fișiere găsite)...{RESET}", flush=True)

        contor_total_procesat = 0
        for file_info in fisiere_an:
            # Sărim peste ce e marcat deja ca procesat (dacă nu s-a dat reset)
            if file_info.get('description', '') == 'processed=true':
                continue

            try:
                cerere = service.files().get_media(fileId=file_info['id'])
                fh = io.BytesIO()
                descarcare = MediaIoBaseDownload(fh, cerere)
                gata = False
                while not gata:
                    _, gata = descarcare.next_chunk()
                
                xml_text = fh.getvalue().decode("utf-8", errors="ignore")
                
                for em in regex_emitent.findall(xml_text):
                    val = em.strip()
                    if val: emitenti_gasiti.add(val)
                    
                for ta in regex_tip_act.findall(xml_text):
                    val = ta.strip()
                    if val: tipuri_acte_gasite.add(val)

                # Marcare ca procesat pe Google Drive
                service.files().update(
                    fileId=file_info['id'],
                    body={'description': 'processed=true'},
                    fields='id',
                    supportsAllDrives=True
                ).execute()
                
                contor_total_procesat += 1

                if contor_total_procesat % 100 == 0:
                    print(f"   📊 [Progres An {target_year}] Procesate: {contor_total_procesat}/{len(fisiere_an)}", flush=True)

            except Exception as e:
                continue

        print(f"✅ [An Gata {target_year}] Total procesat în această sesiune: {contor_total_procesat}", flush=True)

    string_ani = "_".join([str(a) for a in ani_procesare])
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
            
    print(f"{VERDE}✅ [Gata] Fragmentul pentru anii {string_ani} a fost salvat complet!{RESET}", flush=True)

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
        print(f"{ROSU}🛑 Eroare: Lipsesc anii ca parametru!{RESET}")
        sys.exit(1)
        
    drive_service = get_drive_service()
    extrage_taguri_din_matrice(drive_service, ani_finali)
