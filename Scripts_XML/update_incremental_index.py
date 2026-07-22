import os
import sys
import time
import json
import re
from pathlib import Path

# ==============================================================================
# CONFIGURARE CĂI DE IMPORT
# ==============================================================================
DIRECTOR_CURENT = Path(__file__).resolve().parent
RADACINA_PROIECT = DIRECTOR_CURENT.parent

if str(RADACINA_PROIECT) not in sys.path:
    sys.path.insert(0, str(RADACINA_PROIECT))
if str(DIRECTOR_CURENT) not in sys.path:
    sys.path.insert(0, str(DIRECTOR_CURENT))

from drive_config import FOLDER_TEMP_INDEXES_ID, get_list_params, get_file_params

try:
    import XML_INDEX_READER
except ImportError:
    from Scripts_XML import XML_INDEX_READER

try:
    import build_index
except ImportError:
    from Scripts_XML import build_index


def curata_micro_indecsi_procesati(service):
    """
    Șterge fișierele temporare de micro-index (temp_index_*.json) din Drive 
    după ce au fost consolidate în Master Index.
    """
    try:
        query_temp = f"'{FOLDER_TEMP_INDEXES_ID}' in parents and name contains 'temp_index_' and trashed = false"
        res = service.files().list(**get_list_params(q=query_temp, fields="files(id, name)")).execute()
        files = res.get("files", [])

        if files:
            print(f"🧹 Curățare {len(files)} fișiere de micro-index temporare...", flush=True)
            for f in files:
                try:
                    params = get_file_params(fileId=f["id"])
                    params["body"] = {"trashed": True}
                    service.files().update(**params).execute()
                except Exception as e:
                    print(f"⚠️ Nu s-a putut șterge micro-indexul {f['name']}: {e}", flush=True)
            print("✅ Micro-indecșii temporari au fost curățați cu succes!", flush=True)
    except Exception as e:
        print(f"⚠️ Eroare la curățarea micro-indecșilor: {e}", flush=True)


def main():
    print("============================================================", flush=True)
    print("⚡ PORNIRE REINDEXARE INCREMENTALĂ & IGIENIZARE (EVERY 2 HOURS)", flush=True)
    print("============================================================", flush=True)

    timp_start = time.time()
    service = build_index.get_drive_service()

    # 1. Încărcare stare unificată LIVE
    print("\n1️⃣ Încărcare și consolidare stare LIVE...", flush=True)
    index_virtual = XML_INDEX_READER.obtine_index_virtual(service)
    fisiere_map = index_virtual.get("fisiere", {})

    print(f"📊 Fișiere identificate în stare virtuală: {len(fisiere_map):,}", flush=True)

    # Regex flexibil pentru normalizare semantică
    pattern_xml = re.compile(r"^brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)

    # 2. Grupare semantică după (an, pag)
    print("\n2️⃣ Identificare fișiere corupte (<10B) și dedublare semantică...", flush=True)
    grupuri_semantice = {}
    ids_de_sters = []
    fisiere_mici = 0
    duplicate_detectate = 0

    for nume, meta in fisiere_map.items():
        size = meta.get("size", 0)
        file_id = meta.get("id")

        if size < 10:
            if file_id:
                ids_de_sters.append(file_id)
            fisiere_mici += 1
            continue

        match = pattern_xml.match(nume)
        if match:
            cheie_semantica = f"{match.group(1)}_pag{match.group(2)}"
        else:
            cheie_semantica = nume  # Fallback dacă e un nume atipic

        if cheie_semantica not in grupuri_semantice:
            grupuri_semantice[cheie_semantica] = []
        
        # Salvăm numele împreună cu metadatele
        meta_copie = dict(meta)
        meta_copie["_nume_fisier"] = nume
        grupuri_semantice[cheie_semantica].append(meta_copie)

    # 3. Alegerea câștigătorului per cheie semantică
    master_curat = {"fisiere": {}, "total_fisiere": 0, "last_updated": ""}

    for cheie, variante in grupuri_semantice.items():
        if len(variante) == 1:
            castigator = variante[0]
        else:
            # Preferăm denumirea nouă 'brut_XML_' și data creării cea mai recentă
            variante.sort(
                key=lambda x: (
                    1 if x["_nume_fisier"].startswith("brut_XML_") else 0,
                    x.get("createdTime", "")
                ),
                reverse=True
            )
            castigator = variante[0]
            for dup in variante[1:]:
                if dup.get("id"):
                    ids_de_sters.append(dup["id"])
                    duplicate_detectate += 1

        nume_oficial = castigator.pop("_nume_fisier")
        # Standardizăm denumirea în Master Index dacă era veche
        if nume_oficial.startswith("brut_legislatie_"):
            nume_oficial = nume_oficial.replace("brut_legislatie_", "brut_XML_")

        master_curat["fisiere"][nume_oficial] = castigator

    master_curat["total_fisiere"] = len(master_curat["fisiere"])

    print(f"✅ Fișiere XML valide rămase în Master: {master_curat['total_fisiere']:,}", flush=True)
    if fisiere_mici > 0:
        print(f"🗑️ Fișiere corupte/goale (<10B) marcate pentru coș: {fisiere_mici:,}", flush=True)
    if duplicate_detectate > 0:
        print(f"🗑️ Duplicate marcate pentru coș: {duplicate_detectate:,}", flush=True)

    # 4. Salvare Master Index actualizat
    print("\n3️⃣ Salvare Master Index actualizat pe Google Drive...", flush=True)
    salvat_ok = build_index.salveaza_master_index_xml(
        service,
        master_curat,
        mesaj="Master Index XML Actualizat Incremental"
    )

    if not salvat_ok:
        print("❌ ABORT: Salvarea indexului a eșuat. Se anulează ștergerea din Drive.", flush=True)
        sys.exit(1)

    # 5. Trimitere la coș a duplicatelor
    if ids_de_sters:
        print(f"\n4️⃣ Trimitere la coș #{len(ids_de_sters):,} fișiere neconforme...", flush=True)
        build_index.executa_trash_multi_threaded(ids_de_sters, max_workers=15)

    # 6. Curățare micro-indecși
    print("\n5️⃣ Curățare fișiere temporare de micro-index...", flush=True)
    curata_micro_indecsi_procesati(service)

    durata = round(time.time() - timp_start, 2)
    print("\n============================================================", flush=True)
    print(f"🎉 REINDEXARE INCREMENTALĂ FINALIZATĂ ÎN {durata} SECUNDE!", flush=True)
    print("============================================================", flush=True)


if __name__ == "__main__":
    main()
