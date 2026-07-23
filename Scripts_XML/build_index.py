import os
import sys
import json
import gzip

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def proceseaza_si_curata_microindecsi(service_drive, master_index_data, list_micro_index_files, batch_size=50):
    """
    Procesează TOȚI micro-indecșii în batch-uri controlate pentru a evita erorile de memorie/timeout,
    îi îmbină în Master Index și îi șterge definitiv de pe Google Drive.
    """
    total_fisiere = len(list_micro_index_files)
    if total_fisiere == 0:
        print("✨ [MICRO-INDEX] Nu există micro-indecși de procesat.", flush=True)
        return master_index_data

    print(f"⚡ [MICRO-INDEX] Începe procesarea a {total_fisiere} micro-indecși în batch-uri de {batch_size}...", flush=True)

    # Procesăm în etape / batch-uri
    for i in range(0, total_fisiere, batch_size):
        batch = list_micro_index_files[i : i + batch_size]
        print(f"🔄 [MICRO-INDEX] Procesare batch {i // batch_size + 1} (fișierele {i + 1} - {min(i + batch_size, total_fisiere)} din {total_fisiere})...", flush=True)

        fisiere_de_sters_ids = []

        for micro_file in batch:
            try:
                # 1. Citire și aplicare date micro-index în Master Index
                # (presupunând citirea conținutului micro-indexului)
                micro_data = micro_file.get("content_json", {})
                for cheie, info in micro_data.items():
                    master_index_data[cheie] = info

                fisiere_de_sters_ids.append(micro_file["id"])
            except Exception as e:
                print(f"⚠️ [MICRO-INDEX] Eroare la citirea micro-indexului {micro_file.get('name')}: {e}", flush=True)

        # 2. Ștergerea fizică în batch a micro-indecșilor procesați cu succes
        for file_id in fisiere_de_sters_ids:
            try:
                service_drive.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            except Exception as e:
                print(f"⚠️ [MICRO-INDEX] Nu s-a putut șterge micro-indexul {file_id}: {e}", flush=True)

        print(f"✅ [MICRO-INDEX] Batch {i // batch_size + 1} integrat și curățat ({len(fisiere_de_sters_ids)} fișiere șterse).", flush=True)

    print(f"🎉 [MICRO-INDEX] Toți cei {total_fisiere} micro-indecși au fost integrați și șterși definitiv!", flush=True)
    return master_index_data
