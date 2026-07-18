import os
import sys
import json
import csv
import io
import time
import httpx
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

URL_TEMPLATE = "https://www.monitoruloficial.ro/emonitor/PDF_baza.php?an={an}&numar={numar}{sufix}"

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipsește secretul GOOGLE_SERVICE_ACCOUNT_JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def obtine_sau_creeaza_registru(service, nume_registru, drive_folder_pdf):
    query = f"'{drive_folder_pdf}' in parents and name = '{nume_registru}' and trashed = false"
    existente = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="user"
    ).execute().get("files", [])
    
    fieldnames = ["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"]
    
    if existente:
        file_id = existente[0]["id"]
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        fh.seek(0)
        reader = csv.DictReader(io.StringIO(fh.read().decode("utf-8")))
        return file_id, list(reader)
    else:
        cale_temp = f"temp_init_{nume_registru}"
        with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        
        metadata = {'name': nume_registru, 'parents': [drive_folder_pdf]}
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        nou = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
        os.remove(cale_temp)
        print(f"🆕 [{GREEN}CREAT{RESET}] Registru CSV nou (ID: {nou['id']})")
        return nou["id"], []

def salveaza_registru_in_drive(service, file_id, nume_registru, randuri):
    cale_temp = f"temp_save_{nume_registru}"
    fieldnames = ["numar_baza", "sufix", "status", "dimensiune_kb", "drive_file_id"]
    
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(randuri)
        
    # Mecanism de Retry avansat rezistent la erori HTTP și defecțiuni de rețea (BrokenPipe / OSError)
    for incercare in range(1, 5):
        try:
            media = MediaFileUpload(cale_temp, mimetype="text/csv", resumable=False)
            service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            if os.path.exists(cale_temp):
                os.remove(cale_temp)
            return file_id
        except HttpError as err:
            if err.resp.status in [403, 429]:
                timp_asteptare = incercare * 5
                print(f"   🛑 {YELLOW}[Limită Google API]{RESET} Serverul Google e suprasolicitat. Reîncercare în {timp_asteptare}s...")
                time.sleep(timp_asteptare)
            else:
                if os.path.exists(cale_temp):
                    os.remove(cale_temp)
                raise err
        except (OSError, Exception) as net_err:
            timp_asteptare = incercare * 6
            print(f"   ⚠️ {RED}[Eroare Conexiune Google API - Broken Pipe]{RESET} ({net_err}). Refacere sesiune în {timp_asteptare}s...")
            time.sleep(timp_asteptare)
            try:
                # Re-autentificăm forțat instanța deoarece socket-ul sau tokenul intern a fost închis brutal de rețea
                service = obtine_drive()
            except Exception as e:
                print(f"   ❌ Eșec la re-autentificare Drive: {e}")
                
    if os.path.exists(cale_temp):
        os.remove(cale_temp)
    return file_id

def adauga_sau_updateaza_rand(randuri, nr, sufix, status, dim_kb="", d_id=""):
    gasit = False
    for idx, r in enumerate(randuri):
        if int(r["numar_baza"]) == nr and r["sufix"] == sufix:
            randuri[idx] = {"numar_baza": str(nr), "sufix": sufix, "status": status, "dimensiune_kb": dim_kb, "drive_file_id": d_id}
            gasit = True
            break
    if not gasit:
        randuri.append({"numar_baza": str(nr), "sufix": sufix, "status": status, "dimensiune_kb": dim_kb, "drive_file_id": d_id})

def proceseaza_an_faza(client, service, an, faza, drive_folder_pdf):
    print(f"\n🚀 Pornire Faza **{faza}** pentru anul {YELLOW}{an}{RESET}")
    
    nume_registru = f"status_{an}.csv"
    file_id_registru, randuri_registru = obtine_sau_creeaza_registru(service, nume_registru, drive_folder_pdf)
    
    este_anul_curent_real = (str(an) == "2026")
    are_eoy = any(r["status"] == "EndOfYear" for r in randuri_registru)
    
    if faza == 1 and are_eoy and not este_anul_curent_real:
        print(f"🛑 [SKIP FAZA 1] Anul istoric {an} are deja marcajul EndOfYear în registru.")
        return file_id_registru

    deja_procesate = set()
    numere_valide_faza1 = set()
    ultimul_numar_valid = None

    for r in randuri_registru:
        cheie = (int(r["numar_baza"]), r["sufix"])
        if r["status"] == "descarcat":
            deja_procesate.add(cheie)
            if r["sufix"] == "":
                numere_valide_faza1.add(int(r["numar_baza"]))
                ultimul_numar_valid = int(r["numar_baza"])
        elif r["status"] == "EndOfYear" and r["sufix"] == "":
            ultimul_numar_valid = int(r["numar_baza"])

    download_counter = 0
    consecutive_404 = 0
    
    for nr in range(1, 1301):
        if faza == 2 and nr not in numere_valide_faza1:
            if not este_anul_curent_real:
                continue
            elif ultimul_numar_valid and nr > (ultimul_numar_valid + 2):
                break

        if faza == 1:
            sufixe_de_verificat = [""]
        else:
            sufixe_de_verificat = []
            
            # Secvența alfabetică
            for litera in ["a", "b", "c", "d"]:
                if (nr, litera) in deja_procesate:
                    continue
                url = URL_TEMPLATE.format(an=an, numar=nr, sufix=litera)
                try:
                    res = client.head(url)
                    exista = (res.status_code == 200 and "application/pdf" in res.headers.get("content-type", "").lower())
                except:
                    exista = False
                if exista:
                    sufixe_de_verificat.append(litera)
                else:
                    break
            
            # Secvența latină
            for latina in ["bis", "tris", "quater"]:
                if (nr, latina) in deja_procesate:
                    continue
                url = URL_TEMPLATE.format(an=an, numar=nr, sufix=latina)
                try:
                    res = client.head(url)
                    exista = (res.status_code == 200 and "application/pdf" in res.headers.get("content-type", "").lower())
                except:
                    exista = False
                if exista:
                    sufixe_de_verificat.append(latina)
                else:
                    break
                    
            # Ediția Specială (S)
            if (nr, "S") not in deja_procesate:
                sufixe_de_verificat.append("S")

        a_avut_loc_modificare = False

        for sufix in sufixe_de_verificat:
            nume_afisare_sufix = f"_{sufix}" if sufix else ""
            nume_pdf = f"MO_PI_{an}_{nr}{nume_afisare_sufix}.pdf"
            url = URL_TEMPLATE.format(an=an, numar=nr, sufix=sufix)
            cale_pdf_temp = f"temp_{nume_pdf}"
            
            print(f"⏳ [{an} Faza {faza}] Descarcă {nume_pdf}...")
            descarcat_ok = False
            status_special = None
            
            try:
                response = client.get(url)
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "").lower()
                    if "application/pdf" in content_type:
                        with open(cale_pdf_temp, "wb") as f_pdf:
                            f_pdf.write(response.content)
                        descarcat_ok = True
                    else:
                        status_special = "404_NotFound"
                elif response.status_code == 404:
                    status_special = "404_NotFound"
                elif response.status_code in [500, 502, 503, 504]:
                    status_special = f"SERVER_ERROR_{response.status_code}"
                else:
                    status_special = f"HTTP_ERROR_{response.status_code}"
            except Exception as e:
                print(f"   {RED}⚠️ Eroare rețea server MO: {e}{RESET}")
                status_special = "NETWORK_OVERLOAD"
                
            if este_anul_curent_real and status_special in ["NETWORK_OVERLOAD", "SERVER_ERROR_500", "SERVER_ERROR_502", "SERVER_ERROR_503", "SERVER_ERROR_504"]:
                print(f"   ⚠️ {YELLOW}[SKIP PROTECTIV 2026]{RESET} Server suprasolicitat la {nume_pdf}. Abandonăm temporar.")
                time.sleep(1.5)
                continue

            if descarcat_ok and os.path.exists(cale_pdf_temp) and os.path.getsize(cale_pdf_temp) > 2000:
                dimensiune_bytes = os.path.getsize(cale_pdf_temp)
                dimensiune_kb = f"{dimensiune_bytes / 1024:.1f}"
                
                try:
                    drive_id = incarca_pdf_in_drive(service, cale_local_pdf=cale_pdf_temp, nume_pdf=nume_pdf, drive_folder_pdf=drive_folder_pdf)
                    print(f"   {GREEN}✓ Succes ({dimensiune_kb} KB) -> ID: {drive_id}{RESET}")
                    
                    adauga_sau_updateaza_rand(randuri_registru, nr, sufix, "descarcat", dimensiune_kb, drive_id)
                    a_avut_loc_modificare = True
                    
                    if sufix == "":
                        consecutive_404 = 0
                        ultimul_numar_valid = nr
                    download_counter += 1
                except Exception as e:
                    print(f"   {RED}⚠️ Eroare Drive la încărcare: {e}{RESET}")
                finally:
                    if os.path.exists(cale_pdf_temp):
                        os.remove(cale_pdf_temp)
            else:
                if os.path.exists(cale_pdf_temp):
                    os.remove(cale_pdf_temp)
                    
                status_salvare = status_special if status_special else "Inexistent"
                adauga_sau_updateaza_rand(randuri_registru, nr, sufix, status_salvare)
                a_avut_loc_modificare = True
                
                if faza == 1:
                    if status_special == "404_NotFound":
                        consecutive_404 += 1
                    elif status_special == "NETWORK_OVERLOAD" or (status_special and "SERVER_ERROR" in status_special):
                        pass
                    else:
                        consecutive_404 += 1
                
                if faza == 1:
                    if este_anul_curent_real:
                        if consecutive_404 >= 15:
                            print(f"\n🛑 {YELLOW}[FRÂNĂ AN CURENT 2026]{RESET} S-au detectat {consecutive_404} goluri consecutive. Suntem la zi.")
                            file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                            return file_id_registru
                    else:
                        if consecutive_404 >= 5:
                            numar_marcare = ultimul_numar_valid if ultimul_numar_valid is not None else 0
                            print(f"\n🛑 {YELLOW}[EARLY EXIT AN ISTORIC {an}]{RESET} S-au găsit 5 erori 404 consecutive reale.")
                            
                            for eliminat in range(nr - 4, nr + 1):
                                if eliminat > numar_marcare:
                                    randuri_registru = [r for r in randuri_registru if not (int(r["numar_baza"]) == eliminat and r["sufix"] == "")]
                                
                            adauga_sau_updateaza_rand(randuri_registru, numar_marcare, "", "EndOfYear")
                            file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                            return file_id_registru
            
            time.sleep(1.2)
            
            if download_counter > 0 and download_counter % 200 == 0:
                print(f"\n☕ [Pauză Antistres IP] 5 minute...")
                time.sleep(300)
                download_counter = 0

        # Salvăm fișierul de status în Drive DOAR O DATĂ per număr complet de monitor procesat
        if a_avut_loc_modificare:
            file_id_registru = salveaza_registru_in_drive(service, file_id_registru, nume_registru, randuri_registru)
                
    return file_id_registru

def incarca_pdf_in_drive(service, cale_local_pdf, nume_pdf, drive_folder_pdf):
    metadata = {'name': nume_pdf, 'parents': [drive_folder_pdf]}
    media = MediaFileUpload(cale_local_pdf, mimetype="application/pdf", resumable=True)
    fisier_drive = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
    return fisier_drive.get("id")

def executa_sincronizare():
    an_raw = os.getenv("AN_CURENT")
    drive_folder_pdf = os.getenv("DRIVE_FOLDER_PDF")

    if not an_raw or not drive_folder_pdf:
        print(f"{RED}❌ EROARE CRITICĂ: Variabile de mediu incomplete.{RESET}")
        sys.exit(1)
        
    an = int(an_raw.strip())
    print(f"🌍 {GREEN}Procesare individuală protejată anti-403-API și BrokenPipe. An:{RESET} {an}")
    service = obtine_drive()
    
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(30.0, connect=15.0)
    
    with httpx.Client(limits=limits, timeout=timeout, follow_redirects=True) as client:
        print(f"\n=======================================================")
        print(f"📅 SCANARE BATCH ANUL: {an}")
        print(f"=======================================================")
        
        service = obtine_drive() # Ne asigurăm că avem o sesiune fresh la începutul jobului
        proceseaza_an_faza(client, service, an, faza=1, drive_folder_pdf=drive_folder_pdf)
        proceseaza_an_faza(client, service, an, faza=2, drive_folder_pdf=drive_folder_pdf)

    print(f"\n🏁 {GREEN}Rularea optimizată pentru anul {an} s-a terminat cu succes!{RESET}")

if __name__ == "__main__":
    executa_sincronizare()
