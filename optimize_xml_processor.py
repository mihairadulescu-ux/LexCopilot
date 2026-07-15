def main():
    service = get_drive_service()
    
    # 1. Listăm toate fișierele XML din folderul sursă
    print(f"Se listează fișierele din folderul XML (ID: {XML_FOLDER_ID})...")
    
    try:
        results = service.files().list(
            q=f"'{XML_FOLDER_ID}' in parents and trashed = false",
            fields="files(id, name)",
            pageSize=1000,
            # Parametrii critici pentru a permite Service Account-ului să vadă folderele partajate:
            includeItemsFromAllDrives=True,
            supportsAllDrives=True
        ).execute()
        
    except Exception as e:
        print(f"[Eroare listare] Nu s-a putut accesa folderul. Detalii API: {str(e)}")
        return
    
    files = results.get('files', [])
    if not files:
        print("Nu s-a găsit niciun fișier XML în folder.")
        print("Verifică dacă fișierele din folder nu sunt cumva în Trash sau dacă ID-ul folderului este corect.")
        return

    print(f"Succes! Am găsit {len(files)} fișiere în total.")
    
    all_records = []
    processed_count = 0
    drive_csv_id = None
    
    # Ștergem fișierul CSV local anterior dacă există
    if os.path.exists(LOCAL_CSV_PATH):
        os.remove(LOCAL_CSV_PATH)
        
    # 2. Procesăm fișierele folosind cele 4 sesiuni paralele
    print(f"Pornim procesarea asincronă cu {NUM_WORKERS} lucrători...")
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {
            executor.submit(download_and_parse, f['id'], f['name'], service): f['name']
            for f in files
        }
        
        for future in as_completed(futures):
            file_name = futures[future]
            records = future.result()
            all_records.extend(records)
            processed_count += 1
            
            if processed_count % 100 == 0:
                print(f"Progres: {processed_count}/{len(files)} fișiere citite...")
                
            if processed_count % SAVE_INTERVAL == 0 or processed_count == len(files):
                print(f"\n[Prag atins] Salvare intermediară la {processed_count} fișiere...")
                
                if all_records:
                    headers = set()
                    for r in all_records:
                        headers.update(r.keys())
                    headers = sorted(list(headers))
                    
                    with open(LOCAL_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=headers)
                        writer.writeheader()
                        writer.writerows(all_records)
                    
                    drive_csv_id = save_to_drive(service, LOCAL_CSV_PATH, drive_csv_id)
                    print(f"[Sync finalizat] Date salvate până la fișierul #{processed_count}.\n")
                else:
                    print("Nu există date de salvat în acest calup.")

    if os.path.exists(LOCAL_CSV_PATH):
        os.remove(LOCAL_CSV_PATH)

    print(f"Procesare completă! Toate cele {processed_count} fișiere au fost integrate în CSV.")
