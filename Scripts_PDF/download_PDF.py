import os
import sys
import time
import random
import io
import json
import csv
import re
from pathlib import Path
import httpx
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

VERDE = "\033[92m"
GALBEN = "\033[93m"
ROSU = "\033[91m"
RESET = "\033[0m"

TARGET_FOLDER_ID = os.getenv("DRIVE_FOLDER_PDF")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
]


def obtine_drive():
    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in os.environ:
        raise EnvironmentError("❌ Lipseste secretul account JSON!")
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def scaneaza_fisiere_fizice_drive(service, folder_id, an):
    gasesc_fizic = set()
    query = (
        f"'{folder_id}' in parents and "
        f"name contains 'MO_PI_{an}_' and trashed = false"
    )
    page_token = None

    while True:
        try:
            response = service.files().list(
                q=query, spaces='drive',
                fields="nextPageToken, files(name, mimeType)",
                pageToken=page_token, pageSize=1000, supportsAllDrives=True,
                includeItemsFromAllDrives=True, corpora="allDrives"
            ).execute()

            for f in response.get("files", []):
                nume = f.get("name", "")
                mime_type = f.get("mimeType", "")
                if nume.lower().endswith('.pdf') and \
                   mime_type == 'application/pdf':
                    gasesc_fizic.add(nume)

            page_token = response.get("nextPageToken", None)
            if not page_token:
                break
        except Exception as e:
            print(f"{ROSU}⚠️ Erroare scanare: {e}{RESET}", flush=True)
            break
    return gasesc_fizic


def incarc_registru_an(service, folder_id, an):
    registru_local = {}
    nume_csv = f"status_{an}.csv"
    query = (
        f"'{folder_id}' in parents and "
        f"name = '{nume_csv}' and trashed = false"
    )

    try:
        files = service.files().list(
            q=query, spaces='drive', fields='files(id)',
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            corpora="allDrives"
        ).execute().get('files', [])

        if files:
            request = service.files().get_media(fileId=files[0]['id'])
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)

            raw_data = fh.getvalue().decode('utf-8')
            reader = csv.reader(io.StringIO(raw_data), delimiter=",")
            next(reader, None)

            for rand in reader:
                if len(rand) >= 3:
                    nr_baza = rand[0]
                    sufix = rand[1]
                    status = rand[2]
                    if sufix:
                        cheie = f"MO_PI_{an}_{nr_baza}{sufix}.pdf"
                    else:
                        cheie = f"MO_PI_{an}_{nr_baza}.pdf"
                    registru_local[cheie] = status
    except Exception:
        pass
    return registru_local


def salveaza_registru_an(service, folder_id, an, registru_local):
    nume_csv = f"status_{an}.csv"
    print(f"💾 Sincronizare index zonal [{nume_csv}]...", flush=True)

    randuri_csv = []
    for nume_fisier, status in sorted(registru_local.items()):
        m = re.search(r"MO_PI_(\d{4})_([A-Za-z0-9]+)\.pdf", nume_fisier)
        if m:
            numar_complet = m.group(2)
            match_baza = re.match(r"^(\d+)", numar_complet)
            if match_baza:
                nr_baza = match_baza.group(1)
                sufix = numar_complet[len(nr_baza):]
                randuri_csv.append([
                    nr_baza, sufix, status,
                    "0" if status == "neexistent" else "recalculat", ""
                ])

    cale_temp = f"temp_sync_{nume_csv}"
    with open(cale_temp, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow([
            "numar_baza", "sufix", "status",
            "dimensiune_kb", "drive_file_id"
        ])
        writer.writerows(randuri_csv)

    try:
        media = MediaFileUpload(cale_temp, mimetype="text/csv")
        query = (
            f"'{folder_id}' in parents and "
            f"name = '{nume_csv}' and trashed = false"
        )
        existing = service.files().list(
            q=query, spaces='drive', fields='files(id)',
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            corpora="allDrives"
        ).execute().get('files', [])

        if existing:
            service.files().update(
                fileId=existing[0]['id'],
                media_body=media, supportsAllDrives=True
            ).execute()
        else:
            meta = {"name": nume_csv, "parents": [folder_id]}
            service.files().create(
                body=meta, media_body=media,
                supportsAllDrives=True
            ).execute()

        if os.path.exists(cale_temp):
            os.remove(cale_temp)
        print("    ✅ Punct de salvare executat.", flush=True)
    except Exception as e:
        print(f"{ROSU}❌ Eroare salvare CSV: {e}{RESET}", flush=True)


def ruleaza_sincronizare_an_specific(an):
    if not TARGET_FOLDER_ID:
        return

    url_tmpl = "https://monitoruloficial.ro/Monitorul-Oficial--PI--{num}--{an}.html"
    service = obtine_drive()
    director_temp = Path("./temp_pdf")
    director_temp.mkdir(exist_ok=True)
    timeout_resilient = httpx.Timeout(timeout=45.0, connect=15.0)

    MAX_NUMERE_AN = 1350

    print(f"\n{VERDE}🔄 Incarcare date an {an}...{RESET}", flush=True)
    registru_an = incarc_registru_an(service, TARGET_FOLDER_ID, an)
    fisiere_existente_drive = scaneaza_fisiere_fizice_drive(
        service, TARGET_FOLDER_ID, an
    )
    print(f"📊 Detecție: {len(fisiere_existente_drive)} PDF-uri.", flush=True)

    for nume_f in fisiere_existente_drive:
        if registru_an.get(nume_f) != "descarcat":
            registru_an[nume_f] = "descarcat"

    numere_simple_gasite = []
    for nume_f, status in registru_an.items():
        if status == "descarcat":
            m = re.search(r"MO_PI_\d{4}_(\d+)\.pdf$", nume_f)
            if m:
                numere_simple_gasite.append(int(m.group(1)))

    ultimul_numar_baza_cert = (
        max(numere_simple_gasite) if numere_simple_gasite else 0
    )
    if ultimul_numar_baza_cert > 0:
        print(
            f"🎯 [Barieră] Ultimul număr sigur: {ultimul_numar_baza_cert}.",
            flush=True
        )

    coada_an = []

    for n in range(1, MAX_NUMERE_AN + 1):
        f_simplu = f"MO_PI_{an}_{n}.pdf"
        if f_simplu not in registru_an or registru_an[f_simplu] == "":
            coada_an.append({"numar": str(n), "nume": f_simplu})
            continue

        if registru_an[f_simplu] == "descarcat":
            if ultimul_numar_baza_cert > 0 and n > ultimul_numar_baza_cert:
                continue

            f_bis = f"MO_PI_{an}_{n}Bis.pdf"
            f_special = f"MO_PI_{an}_{n}S.pdf"
            if f_special not in registru_an or registru_an[f_special] == "":
                coada_an.append({"numar": f"{n}S", "nume": f_special})
            if f_bis not in registru_an or registru_an[f_bis] == "":
                coada_an.append({"numar": f"{n}Bis", "nume": f_bis})
            elif registru_an[f_bis] == "descarcat":
                f_tris = f"MO_PI_{an}_{n}Tris.pdf"
                if f_tris not in registru_an or registru_an[f_tris] == "":
                    coada_an.append({"numar": f"{n}Tris", "nume": f_tris})
                elif registru_an[f_tris] == "descarcat":
                    f_quater = f"MO_PI_{an}_{n}Quater.pdf"
                    if f_quater not in registru_an or \
                       registru_an[f_quater] == "":
                        coada_an.append({
                            "numar": f"{n}Quater", "nume": f_quater
                        })

    total_an = len(coada_an)
    if total_an == 0:
        print(f"🎉 Anul {an} este complet sincronizat.", flush=True)
        return

    print(f"🚀 Verificare ierarhică: {total_an} fișiere...", flush=True)

    modificari_nesalvate = 0
    modificari_detectate = False
    erori_consecutive_retea = 0

    for idx, item in enumerate(coada_an, 1):
        nume_pdf = item["nume"]
        url = url_tmpl.format(num=item["numar"], an=an)

        if nume_pdf in fisiere_existente_drive:
            registru_an[nume_pdf] = "descarcat"
            modificari_detectate = True
            continue

        print(f"⏳ [{idx}/{total_an}] Solicitare ({an}): {nume_pdf}...",
              flush=True)
        time.sleep(random.uniform(1.0, 2.2))

        try:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Referer": "https://monitoruloficial.ro/"
            }
            with httpx.Client(headers=headers, timeout=timeout_resilient,
                              follow_redirects=True) as client:
                response = client.get(url)
                erori_consecutive_retea = 0

                if response.status_code == 404:
                    print("    ❌ [404] Neexistent sigur.", flush=True)
                    registru_an[nume_pdf] = "neexistent"
                    modificari_detectate = True
                    modificari_nesalvate += 1
                elif response.status_code == 200:
                    c_type = response.headers.get("Content-Type", "").lower()
                    if "application/pdf" in c_type or \
                       len(response.content) > 30000:
                        cale_l = director_temp / nume_pdf
                        with open(cale_l, "wb") as f_out:
                            f_out.write(response.content)

                        media = MediaFileUpload(
                            str(cale_l), mimetype='application/pdf',
                            resumable=True
                        )
                        meta_drive = {
                            'name': nume_pdf, 'parents': [TARGET_FOLDER_ID]
                        }
                        service.files().create(
                            body=meta_drive, media_body=media,
                            supportsAllDrives=True
                        ).execute()
                        cale_l.unlink()
                        print(
                            f"    📥 {VERDE}[DESCARCAT]{RESET} PDF salvat! ✅",
                            flush=True
                        )
                        registru_an[nume_pdf] = "descarcat"
                        modificari_detectate = True
                        modificari_nesalvate += 1
                    else:
                        text_primit = response.text
                        if "flowpaper_viewer" in text_primit or \
                           "flowpaper" in text_primit or \
                           "<title>Monitorul Oficial" in text_primit:
                            print(
                                "    ❌ [HTML Empty Viewer] Neexistent.",
                                flush=True
                            )
                            registru_an[nume_pdf] = "neexistent"
                            modificari_detectate = True
                            modificari_nesalvate += 1
                        else:
                            print("    ⚠️ [HTML Atipic] Skip.", flush=True)
                            continue
                else:
                    print(f"    ⚠️ [Cod HTTP: {response.status_code}] Skip.",
                          flush=True)
                    continue

            if modificari_nesalvate >= 10:
                salveaza_registru_an(service, TARGET_FOLDER_ID, an, registru_an)
                modificari_nesalvate = 0

        except Exception as e:
            erori_consecutive_retea += 1
            err_msg = str(e)[:80]
            print(
                f"    ❌ {ROSU}[Eroare Rețea]{RESET} Detalii: {err_msg}",
                flush=True
            )

            if modificari_nesalvate > 0:
                print("🚨 Instabil! Forțăm salvarea datelor...", flush=True)
                salveaza_registru_an(service, TARGET_FOLDER_ID, an, registru_an)
                modificari_nesalvate = 0

            if erori_consecutive_retea >= 3:
                print(
                    f"🛑 {ROSU}Blocaj server (3 erori). "
                    f"Oprim execuția.{RESET}",
                    flush=True
                )
                sys.exit(0)

            print("⏳ Așteptăm 15 secunde reîncercare...", flush=True)
            time.sleep(15)
            continue

    if modificari_detectate and modificari_nesalvate > 0:
        salveaza_registru_an(service, TARGET_FOLDER_ID, an, registru_an)


if __name__ == "__main__":
    an_tinta = (
        sys.argv[1] if len(sys.argv) > 1 else os.getenv("AN_TINTA", "2000")
    )
    print(f"🎯 [DOWNLOAD] Pornire pentru anul: {an_tinta}")
    ruleaza_sincronizare_an_specific(int(an_tinta))
