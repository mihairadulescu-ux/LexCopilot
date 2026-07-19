import os
import sys
import csv
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ======================================================================
# CONFIGURARE ȘI CONEXIUNE GOOGLE DRIVE
# ======================================================================
def obtine_serviciu_drive():
    """Inițializează clientul API Google Drive."""
    info_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    foldere_brut = os.getenv("DRIVE_FOLDER_XML")
    
    if not info_json or not foldere_brut:
        print("🛑 [Eroare] Lipsesc credențialele sau folderul XML în mediu!")
        sys.exit(1)
        
    # Spargem lista de foldere prin virgulă
    liste_foldere = [f.strip() for f in foldere_brut.split(",") if f.strip()]
    
    try:
        credențiale = service_account.Credentials.from_service_account_info(
            json.loads(info_json),
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=credențiale), liste_foldere
    except Exception as e:
        print(f"🛑 Eroare autentificare Google Drive: {e}")
        sys.exit(1)

# ======================================================================
# EXTRAGERE TAGURI DIN FIȘIERELE XML (CONVENȚIE: brut_legislatie_{an}_)
# ======================================================================
def extrage_taguri_din_matrice(serviciu, foldere_drive, ani_procesare):
    import xml.etree.ElementTree as ET
    from googleapiclient.http import MediaIoBaseDownload
    import io

    emitenti_gasiti = set()
    tipuri_acte_gasite = set()

    for an in ani_procesare:
        print(f"\n⚡ Încep scanarea istorică pentru anul: {an}")
        fișiere_an = []

        # Parcurgem cele 4 foldere folosind startsWith (antiglonț pe underscore)
        for idx, id_folder in enumerate(foldere_drive, 1):
            print(f"🔍 Căutare în discul {idx}/{len(foldere_drive)} (ID: {id_folder[:8]}...)...")
            interogare = f"'{id_folder}' in parents and name startsWith 'brut_legislatie_{an}_' and mimeType = 'text/xml' and trashed = false"
            
            try:
                pag_token = None
                while True:
                    rezultat = serviciu.files().list(
                        q=interogare,
                        fields="nextPageToken, files(id, name)",
                        pageSize=1000,
                        pageToken=pag_token
                    ).execute()
                    
                    fișiere_an.extend(rezultat.get('files', []))
                    pag_token = rezultat.get('nextPageToken')
                    if not pag_token:
                        break
            except Exception as e:
                print(f"⚠️ Atenție: Nu s-a putut scana discul {idx}: {e}")

        print(f"📦 Am descoperit în total {len(fișiere_an)} fișiere XML pentru anul {an} în toate discurile.")

        # Procesăm fiecare XML localizat în memorie
        for idx_f, f in enumerate(fișiere_an, 1):
            if idx_f % 100 == 0 or idx_f == len(fișiere_an):
                print(f"⚙️ Procesare documente: {idx_f}/{len(fișiere_an)}...")
                
            try:
                cerere = serviciu.files().get_media(fileId=f['id'])
                fh = io.BytesIO()
                descarcare = MediaIoBaseDownload(fh, cerere)
                gata = False
                while not gata:
                    _, gata = descarcare.next_chunk()
                
                conținut_xml = fh.getvalue()
                radacina = ET.fromstring(conținut_xml)
                
                # Colectăm Emitent și TipAct din structura XML a actului
                for item in radacina.findall(".//Act"): 
                    emitent = item.find("Emitent")
                    tip_act = item.find("TipAct")
                    
                    if emitent is not None and emitent.text:
                        emitenti_gasiti.add(emitent.text.strip())
                    if tip_act is not None and tip_act.text:
                        tipuri_acte_gasite.add(tip_act.text.strip())
                        
            except Exception as e:
                continue

    # Salvare fragmente locale în CSV-uri
    string_ani = "_".join(ani_procesare)
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
            
    print(f"✅ Fragmente exportate cu succes: {cale_emitenti} și {cale_acte}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("🛑 Eroare: Lipsesc anii ca parametru!")
        sys.exit(1)
        
    argumente = sys.argv[1:]
    if len(argumente) == 1 and " " in argumente[0]:
        ani = argumente[0].split()
    else:
        ani = argumente
        
    print(f"🎯 [Dictionare] Pornire procesare pentru anii: {ani}")
    client_drive, listă_foldere = obtine_serviciu_drive()
    extrage_taguri_din_matrice(client_drive, listă_foldere, ani)
