# ==============================================================================
# 📌 CUM SE APELEAZĂ DIN ALTE SCRIPTURI (QUICK REFERENCE):
#
# from micro_index_writer import trimite_update_index_temporar, raporteaza_fisiere_sterse
# 
# # La final sau per batch apelezi:
# trimite_update_index_temporar(service, "downloaded", lista_fisiere_salvate)
# ==============================================================================

import os
import json
import uuid
from datetime import datetime, timezone
from googleapiclient.http import MediaFileUpload

CALE_TEMP_LOCAL = "temp_index_local.json"
DEFAULT_TEMP_FOLDER_ID = "1NduQgFpbAPIPEEc7tvcfR6gLI6LuxfYR"


def trimite_update_index_temporar(service, nume_flag, lista_fisiere, stare_flag=True):
    """
    Creează și încarcă un micro-index temporar în folderul 'TEMPORARY_XML_INDEXES' din Drive.
    """
    if not lista_fisiere:
        print("ℹ️ [MicroIndex] Lista de fișiere este goală. Niciun micro-index generat.", flush=True)
        return

    folder_temp_id = os.getenv("TEMPORARY_XML_INDEXES", "").strip() or DEFAULT_TEMP_FOLDER_ID
    if not folder_temp_id:
        print("⚠️ [MicroIndex] Variabila 'TEMPORARY_XML_INDEXES' nu este setată! Micro-indexul nu a fost salvat.", flush=True)
        return

    # Structurăm modificările de flag-uri
    flag_updates = {}
    for nume_fisiere in lista_fisiere:
        flag_updates[nume_fisiere] = {nume_flag: stare_flag}

    date_micro_index = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_updates": len(flag_updates),
        "flag_updates": flag_updates
    }

    unique_id = str(uuid.uuid4())[:8]
    nume_fisier_remote = f"temp_index_{nume_flag}_{unique_id}.json"

    try:
        with open(CALE_TEMP_LOCAL, "w", encoding="utf-8") as f:
            json.dump(date_micro_index, f, ensure_ascii=False, indent=2)

        file_metadata = {
            'name': nume_fisier_remote,
            'parents': [folder_temp_id]
        }
        media = MediaFileUpload(CALE_TEMP_LOCAL, mimetype='application/json')
        
        service.files().create(
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True
        ).execute()

        print(f"✅ [MicroIndex] Logat în Drive: {nume_fisier_remote} ({len(lista_fisiere)} fișiere cu {nume_flag}={stare_flag})", flush=True)

    except Exception as e:
        print(f"❌ [MicroIndex] Eroare la încărcarea micro-indexului în Drive: {e}", flush=True)
    finally:
        if os.path.exists(CALE_TEMP_LOCAL):
            os.remove(CALE_TEMP_LOCAL)


def raporteaza_fisiere_sterse(service, lista_fisiere_sterse):
    """
    Trimite o notificare către Master Index Builder că anumite fișiere nu mai există pe Drive.
    """
    if not lista_fisiere_sterse:
        return

    folder_temp_id = os.getenv("TEMPORARY_XML_INDEXES", "").strip() or DEFAULT_TEMP_FOLDER_ID
    if not folder_temp_id:
        return

    flag_updates = {}
    for nume_fisiere in lista_fisiere_sterse:
        flag_updates[nume_fisiere] = {"_deleted": True}

    date_micro_index = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_updates": len(flag_updates),
        "flag_updates": flag_updates
    }

    unique_id = str(uuid.uuid4())[:8]
    nume_fisier_remote = f"temp_index_DELETED_{unique_id}.json"

    try:
        with open(CALE_TEMP_LOCAL, "w", encoding="utf-8") as f:
            json.dump(date_micro_index, f, ensure_ascii=False, indent=2)

        file_metadata = {'name': nume_fisier_remote, 'parents': [folder_temp_id]}
        media = MediaFileUpload(CALE_TEMP_LOCAL, mimetype='application/json')
        service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()
        print(f"🗑️ [MicroIndex] Raportate {len(lista_fisiere_sterse)} fișiere șterse către Master Index.", flush=True)
    except Exception as e:
        print(f"❌ [MicroIndex] Eroare raportare ștergeri: {e}", flush=True)
    finally:
        if os.path.exists(CALE_TEMP_LOCAL):
            os.remove(CALE_TEMP_LOCAL)
