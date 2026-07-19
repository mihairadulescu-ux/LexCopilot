import os
import sys
import json

def obtine_serviciu_drive():
    info_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    foldere_brut = os.getenv("DRIVE_FOLDER_XML")
    
    if not info_json or not foldere_brut:
        print("🛑 [Eroare Reset] Lipsesc credențialele sau folderul XML în mediu!")
        sys.exit(1)
        
    liste_foldere = [f.strip() for f in foldere_brut.split(",") if f.strip()]
    
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        credențiale = service_account.Credentials.from_service_account_info(
            json.loads(info_json),
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=credențiale), liste_foldere
    except Exception as e:
        print(f"🛑 Eroare autentificare Google Drive la reset: {e}")
        sys.exit(1)

def ruleaza_reset_flaguri(serviciu, foldere_drive, ani_procesare):
    for an in ani_procesare:
        print(f"\n⚙️ [Reset] Inițiere curățare flaguri pentru anul: {an}")
        fișiere_de_resetat = []
        token_cautare = f"brut_legislatie_{an}_"

        for idx, id_folder in enumerate(foldere_drive, 1):
            print(f"🔍 Listare brută pentru reset în discul {idx}/{len(foldere_drive)}...")
            interogare = f"'{id_folder}' in parents"
            
            try:
                pag_token = None
                while True:
                    rezultat = serviciu.files().list(
                        q=interogare,
                        fields="nextPageToken, files(id, name)",
                        pageSize=1000,
                        pageToken=pag_token
                    ).execute()
                    
                    for f in rezultat.get('files', []):
                        nume_f = f.get('name', '')
                        if token_cautare in nume_f and nume_f.lower().endswith('.xml'):
                            fișiere_de_resetat.append(f)
                            
                    pag_token = rezultat.get('nextPageToken')
                    if not pag_token:
                        break
            except Exception as e:
                print(f"⚠️ Eroare la scanarea discului {idx} pentru reset: {e}")

        total_fișiere = len(fișiere_de_resetat)
        print(f"🎯 Identificate {total_fișiere} fișiere XML în total pentru anul {an}.")

        if total_fișiere == 0:
            print("⏭️ Nu s-au găsit fișiere pentru reset în niciun disc.")
            continue

        print(f"🔄 Se resetează metadatele pentru cele {total_fișiere} fișiere...")
        for idx_f, f in enumerate(fișiere_de_resetat, 1):
            if idx_f % 250 == 0 or idx_f == total_fișiere:
                print(f"   [Progres Reset] {idx_f}/{total_fișiere} modificate...")
                
            try:
                corpurile_metadate = {
                    'description': 'processed=false'
                }
                serviciu.files().update(
                    fileId=f['id'],
                    body=corpurile_metadate,
                    fields='id'
                ).execute()
            except Exception as e:
                continue
                
        print(f"✅ Anul {an} a fost resetat complet pe toate discurile.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("🛑 Eroare Reset: Lipsesc anii ca parametru!")
        sys.exit(1)
        
    argumente = sys.argv[1:]
    if len(argumente) == 1 and " " in argumente[0]:
        ani = argumente[0].split()
    else:
        ani = argumente
        
    print(f"🎯 [Reset Matrice] Pornire curățare flaguri pentru: {ani}")
    client_drive, listă_foldere = obtine_serviciu_drive()
    ruleaza_reset_flaguri(client_drive, listă_foldere, ani)
