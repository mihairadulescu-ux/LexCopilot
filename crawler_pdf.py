import os
import sys
import time
import random
import io
from pathlib import Path
import httpx
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# ======================================================================
# CONFIGURARE GOOGLE DRIVE
# ======================================================================
GOOGLE_DRIVE_FOLDER_ID = "1c8SEo8UrQVe6qgzPFGLXJFiMyLeI-r8D"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
]

def instantiaza_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    import json
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds)

def adu_fisiere_existente_in_drive(drive_service, folder_id):
    existente = {}
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    
    print("   ↳ Scanăm metadatele din Drive...", flush=True)
    while True:
        response = drive_service.files().list(
            q=query, 
            fields="nextPageToken, files(id, name, size)", 
            pageToken=page_token, 
            pageSize=1000,
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
        ).execute()
        
        for f in response.get("files", []):
            nume = f["name"]
            f_id = f["id"]
            size = int(f.get("size", 0))
            status = "ok"
            
            if size == 1:
                status = "dummy_verificabil"
                
            existente[nume] = {"id": f_id, "size": size, "status": status}
            
        page_token = response.get("nextPageToken", None)
        if not page_token:
            break
            
    fisiere_de_verificat = [n for n, v in existente.items() if v["status"] == "dummy_verificabil"]
    if fisiere_de_verificat:
        print(f"   ↳ Am detectat {len(fisiere_de_verificat)} fișiere dummy de 1 byte. Le citim contorul...", flush=True)
        
        for nume in fisiere_de_verificat:
            f_id = existente[nume]["id"]
            try:
                request = drive_service.files().get_media(fileId=f_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    _, done = downloader.next_chunk()
                
                continut = fh.getvalue().decode('utf-8', errors='ignore').strip()
                
                if continut.isdigit() and 1 <= int(continut) <= 5:
                    existente[nume]["status"] = f"dummy_{continut}"
                else:
                    existente[nume]["status"] = "dummy_final"
            except Exception:
                existente[nume]["status"] = "dummy_final"
                
    return existente

def incarca_sau_actualizeaza_in_drive(drive_service, cale_locala, folder_id, file_id_existent=None):
    nume_fisier = cale_locala.name
    media = MediaFileUpload(str(cale_locala), mimetype='application/pdf', resumable=True)
    try:
        if file_id_existent:
            file_drive = drive_service.files().update(fileId=file_id_existent, media_body=media, supportsAllDrives=True).execute()
        else:
            metadata = {'name': nume_fisier, 'parents': [folder_id]}
            file_drive = drive_service.files().create(body=metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
            
        if file_drive.get('id'):
            cale_locala.unlink()
            return True
    except Exception as e:
        print(f"❌ [Drive Err] Eroare scriere/update {nume_fisier}: {e}", flush=True)
    return False

# ======================================================================
# CORE CRAWLER INTELIGENT MULTI-SUFIX CU CONTOR DE TIMP PENTRU BIS
# ======================================================================
def descarca_monitoare_precalculat(an_start=2000, am_stop=2026):
    url_template = "https://monitoruloficial.ro/Monitorul-Oficial--PI--{numar}--{an}.html"
    
    print("🔄 Pasul 1: Conectare la Google Drive și preluare index detaliat...", flush=True)
    try:
        drive_service = instantiaza_drive()
        inventar_drive = adu_fisiere_existente_in_drive(drive_service, GOOGLE_DRIVE_FOLDER_ID)
        print(f"📊 Scanare finalizată. Detectate {len(inventar_drive)} înregistrări în cloud.", flush=True)
    except Exception as e:
        print(f"🛑 Eroare critică la inițializarea Google Drive: {e}", flush=True)
        return

    MAX_NUMERE_AN = 1350 # Ridicat usor pentru anii cu foarte multe numere
    
    print("🧠 Pasul 2: Calculare diferențe și identificare fișiere lipsă...", flush=True)
    coada_descarcare = []
    
    variante_sufixe = [
        {"sufix": "", "tip": "simplu"},
        {"sufix": "Bis", "tip": "bis"},
        {"sufix": "Tris", "tip": "tris"},
        {"sufix": "Quatro", "tip": "quatro"},
        {"sufix": "S", "tip": "s"}
    ]
    
    AN_CURENT_SISTEM = 2026 # Anul de referință pentru limitare dinamică
    
    for an in range(an_start, am_stop + 1):
        numere_existente_an = []
        for f in inventar_drive.keys():
            if f.startswith(f"MO_PI_{an}_"):
                try:
                    num_str = f.split('_')[3].split('.')[0]
                    for suf in ['Bis', 'Tris', 'Quatro', 'S']:
                        num_str = num_str.replace(suf, '')
                    numere_existente_an.append(int(num_str))
                except (IndexError, ValueError):
                    continue
                    
        max_numar_existent = max(numere_existente_an) if numere_existente_an else 0
        
        # CORECTURA MAJORĂ AICI: Pentru anii anteriori scanăm PÂNĂ LA CAPĂT (MAX_NUMERE_AN).
        # Logica cu "max + 30" se aplică DOAR pentru anul în curs ca să nu facă 1000 de cereri 404 aiurea în avans.
        if an < AN_CURENT_SISTEM:
            limita_scanare = MAX_NUMERE_AN
        else:
            # Pentru anul curent, mergem cu maxim 30-50 numere în avans față de cel mai mare găsit
            limita_scanare = min(max_numar_existent + 50, MAX_NUMERE_AN)
            if limita_scanare < 100: # Asigurăm măcar primele 100 dacă anul e abia la început
                limita_scanare = 100
        
        for n in range(1, limita_scanare + 1):
            for var in variante_sufixe:
                numar_complet = f"{n}{var['sufix']}" if var["sufix"] else str(n)
                nume_pdf = f"MO_PI_{an}_{numar_complet}.pdf"
                
                trebuie_descarcat = False
                status_actual = None
                file_id_existent = None
                
                if nume_pdf not in inventar_drive:
                    trebuie_descarcat = True
                else:
                    meta = inventar_drive[nume_pdf]
                    file_id_existent = meta["id"]
                    if var["tip"] == "bis" and meta["status"].startswith("dummy_") and meta["status"] != "dummy_final":
                        trebuie_descarcat = True
                        status_actual = meta["status"]
                
                if trebuie_descarcat:
                    coada_descarcare.append({
                        "an": an, 
                        "numar": numar_complet, 
                        "nume_pdf": nume_pdf, 
                        "tip": var["tip"],
                        "file_id_existent": file_id_existent,
                        "status_actual": status_actual
                    })

    total_lipsa = len(coada_descarcare)
    if total_lipsa == 0:
        print("🎉 Toate fișierele sunt la zi! Nimic de descărcat.", flush=True)
        return
        
    print(f"🚀 Pasul 3: Începem descărcarea a {total_lipsa} fișiere în coadă...", flush=True)
    
    director_temp = Path("./temp_pdf_download")
    director_temp.mkdir(exist_ok=True)
    
    # Timeout standard
    timeout_standard = httpx.Timeout(timeout=45.0, connect=15.0, read=45.0)
    # Timeout uriaș special pentru cărămizile de fișiere (10 minute pentru citire)
    timeout_fisiere_mari = httpx.Timeout(timeout=600.0, connect=20.0, read=600.0)
    
    erori_consecutive_an = {}
    succese_in_an = {} # Contorizăm dacă am reușit să luăm ceva pe anul respectiv
    ani_finalizati = set() 
    fisiere_esuate_protejate = []
    
    for idx, item in enumerate(coada_descarcare, 1):
        an = item["an"]
        numar_cerut = item["numar"]
        nume_pdf = item["nume_pdf"]
        
        este_simplu = item["tip"] == "simplu"
        este_bis = item["tip"] == "bis"
        este_special = item["tip"] not in ["simplu", "bis"]
        
        if an in ani_finalizati:
            continue
            
        print(f"⏳ [{idx}/{total_lipsa}] Se caută pe server: {nume_pdf}...", flush=True)
        
        url = url_template.format(numar=numar_cerut, an=an)
        descarcat_ok = False
        creeaza_fantomă = False
        valoare_fantomă = " "
        
        limită_reincercări = 1 if (este_special or este_bis) else 3
        incercari = 0
        
        cale_locala = director_temp / nume_pdf
        cale_temp = director_temp / f"{nume_pdf}.part"
        
        while incercari < limită_reincercări:
            try:
                time.sleep(random.uniform(1.5, 3.0))
                
                headers = {
                    "User-Agent": random.choice(USER_AGENTS), 
                    "Referer": "https://monitoruloficial.ro/e-monitor/"
                }
                
                with httpx.Client(headers=headers, timeout=timeout_standard, follow_redirects=True) as client:
                    head_res = client.head(url)
                    
                    if head_res.status_code == 404:
                        creeaza_fantomă = True
                        valoare_fantomă = " "
                        if este_simplu:
                            erori_consecutive_an[an] = erori_consecutive_an.get(an, 0) + 1
                            # Prag crescut la 60 și verificăm dacă am luat măcar ceva pe anul ăsta, ca să nu tăiem anii noi
                            if erori_consecutive_an[an] >= 60 and succese_in_an.get(an, 0) > 10:
                                print(f"🏁 [Anulat inteligent] Anul {an} pare finalizat pe server (60 eșecuri consecutive). Sărim restul.", flush=True)
                                ani_finalizati.add(an)
                        break
                    
                    total_bytes = int(head_res.headers.get("Content-Length", 0))
                    
                    timeout_ales = timeout_standard
                    if total_bytes > 90 * 1024 * 1024:
                        timeout_ales = timeout_fisiere_mari
                        print(f"⚠️ Fișier de mari dimensiuni detectat ({total_bytes // 1024 // 1024} MB). Aplicăm streaming direct cu timeout extins (10 min)...", flush=True)

                with httpx.Client(headers=headers, timeout=timeout_ales, follow_redirects=True) as client:
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        
                        if "application/pdf" not in response.headers.get("Content-Type", ""):
                            if este_special:
                                creeaza_fantomă = True
                                valoare_fantomă = " "
                            elif este_bis:
                                creeaza_fantomă = True
                                contor_vechi = int(item["status_actual"].split('_')[1]) if item["status_actual"] else 0
                                urmatorul_contor = contor_vechi + 1
                                valoare_fantomă = str(urmatorul_contor) if urmatorul_contor < 6 else " "
                                print(f"💡 Serverul a trimis HTML. Incrementăm contorul Bis la: {valoare_fantomă}", flush=True)
                            else:
                                print(f"⚠️ Eroare: HTML primit la un fișier SIMPLU. Îl ocolim fără dummy.", flush=True)
                            break
                            
                        if este_simplu:
                            erori_consecutive_an[an] = 0
                            succese_in_an[an] = succese_in_an.get(an, 0) + 1 # Contorizăm succesele
                        
                        if cale_temp.exists():
                            cale_temp.unlink()
                            
                        with open(cale_temp, "wb") as f:
                            for chunk in response.iter_bytes(chunk_size=32768):
                                f.write(chunk)
                                
                        cale_temp.replace(cale_locala)
                        descarcat_ok = True
                        break
                        
            except (httpx.ConnectError, httpx.ReadError, httpx.HTTPStatusError, Exception) as e:
                incercari += 1
                descriere_eroare = str(e) if len(str(e)) < 120 else str(e)[:120] + "..."
                print(f"⚠️ Problemă la descărcare {nume_pdf} (Încercarea {incercari}/{limită_reincercări}): {descriere_eroare}", flush=True)
                
                if este_special:
                    print(f"💡 Eroare la fișier special -> Presupunem neexistent.", flush=True)
                    creeaza_fantomă = True
                    valoare_fantomă = " "
                    break
                elif este_bis:
                    creeaza_fantomă = True
                    contor_vechi = int(item["status_actual"].split('_')[1]) if item["status_actual"] else 0
                    urmatorul_contor = contor_vechi + 1
                    valoare_fantomă = str(urmatorul_contor) if urmatorul_contor < 6 else " "
                    print(f"💡 Eroare conexiune pentru Bis. Incrementăm contorul la: {valoare_fantomă}", flush=True)
                    break
                    
                time.sleep(random.uniform(20.0, 40.0))
                
        if descarcat_ok:
            marime_mb = os.path.getsize(cale_locala) // 1024 // 1024
            print(f"📥 Descărcat cu succes: {nume_pdf} (~{marime_mb} MB)", flush=True)
            if incarca_sau_actualizeaza_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID, item["file_id_existent"]):
                print(f"✅ Sincronizat cu succes în Google Drive.", flush=True)
            time.sleep(random.uniform(2.0, 4.0))
            
        elif creeaza_fantomă:
            if an not in ani_finalizati:
                if cale_temp.exists():
                    cale_temp.unlink()
                
                with open(cale_locala, "w") as f:
                    f.write(valoare_fantomă) 
                
                text_stare = f"contor '{valoare_fantomă}'" if valoare_fantomă != " " else "spațiu final (abandonat)"
                print(f"ℹ️ Actualizăm dummy în Drive ({text_stare}) pentru: {nume_pdf}...", flush=True)
                
                if incarca_sau_actualizeaza_in_drive(drive_service, cale_locala, GOOGLE_DRIVE_FOLDER_ID, item["file_id_existent"]):
                    print(f"📝 Placeholder salvat.", flush=True)
                time.sleep(random.uniform(1.0, 2.0))
        else:
            if an not in ani_finalizati:
                if cale_temp.exists():
                    cale_temp.unlink()
                print(f"⏭️ [Ocolit protejat] Fișierul SIMPLU {nume_pdf} a fost ocolit pentru siguranță.", flush=True)
                fisiere_esuate_protejate.append(nume_pdf)

    if fisiere_esuate_protejate:
        print("\n⚠️ Rularea s-a încheiat. Următoarele fișiere SIMPLU au eșuat temporar și vor fi reîncercate la rularea următoare:", flush=True)
        for f in fisiere_esuate_protejate:
            print(f"  - {f}", flush=True)
    else:
        print("\n🎉 Rularea completă s-a terminat cu succes!", flush=True)

if __name__ == "__main__":
    an_s = int(sys.argv[1]) if len(sys.argv) >= 3 else 2000
    an_f = int(sys.argv[2]) if len(sys.argv) >= 3 else 2026
    descarca_monitoare_precalculat(an_start=an_s, am_stop=an_f)
