# ==========================================================================
    # 3. CONSOLIDARE ÎN MEMORIE, FILTRARE <10 BAȚI ȘI DEDUBLARE SEMANTICĂ
    # ==========================================================================
    print("\n" + "=" * 60, flush=True)
    print("🧠 ANALIZĂ SEMANTICĂ (AN_PAG), FILTRARE <10B ȘI PRESERVARE FLAG-URI...", flush=True)
    print("=" * 60, flush=True)

    pattern_xml = re.compile(r"^brut_(?:XML|legislatie)_(\d+)_pag(\d+)\.xml$", re.IGNORECASE)
    
    # Regrupăm tot inventarul brut după cheia semantică (ex: "1990_pag10")
    grupuri_semantice = {}
    fisiere_mici_eliminate = 0
    ids_de_sters = []

    for nume_fisier, lista_variante in raw_inventory.items():
        # Extragere cheie semantică
        match = pattern_xml.match(nume_fisier)
        if match:
            cheie_semantica = f"{match.group(1)}_pag{match.group(2)}"
        else:
            cheie_semantica = nume_fisier

        if cheie_semantica not in grupuri_semantice:
            grupuri_semantice[cheie_semantica] = []

        for v in lista_variante:
            v_copie = dict(v)
            v_copie["_nume_fisier"] = nume_fisier
            grupuri_semantice[cheie_semantica].append(v_copie)

    master_index = {"fisiere": {}, "total_fisiere": 0, "last_updated": ""}
    stari_recuperate = 0

    for cheie_semantica, lista_variante in grupuri_semantice.items():
        # 1. Filtram mai intai variantele sub 10 Bytți
        variante_valide = [v for v in lista_variante if v["size"] >= 10]
        variante_mici = [v for v in lista_variante if v["size"] < 10]

        for v_mica in variante_mici:
            ids_de_sters.append(v_mica["id"])
            fisiere_mici_eliminate += 1

        if not variante_valide:
            continue

        # 2. Alegem castigatorul (preferăm brut_XML_ și cel mai recent creat)
        if len(variante_valide) == 1:
            castigator = variante_valide[0]
        else:
            variante_valide.sort(
                key=lambda x: (
                    1 if x["_nume_fisier"].startswith("brut_XML_") else 0,
                    x["createdTime"]
                ),
                reverse=True
            )
            castigator = variante_valide[0]
            
            # Duplicatele merg la cos
            for duplicat in variante_valide[1:]:
                ids_de_sters.append(duplicat["id"])

        nume_original = castigator["_nume_fisier"]
        # Preluam starea veche (daca exista sub oricare din denumiri)
        vechea_stare = old_index_map.get(nume_original, {})
        if not vechea_stare:
            # Incercam si denumirea alternativa
            nume_alt = nume_original.replace("brut_legislatie_", "brut_XML_") if "brut_legislatie_" in nume_original else nume_original.replace("brut_XML_", "brut_legislatie_")
            vechea_stare = old_index_map.get(nume_alt, {})

        if vechea_stare:
            stari_recuperate += 1

        # Standardizam numele oficial in Master Index ca brut_XML_
        nume_master = nume_original
        if nume_master.startswith("brut_legislatie_"):
            nume_master = nume_master.replace("brut_legislatie_", "brut_XML_")

        master_index["fisiere"][nume_master] = {
            "id": castigator["id"],
            "folder_id": castigator["folder_id"],
            "createdTime": castigator["createdTime"],
            "size": castigator["size"],
            "downloaded": vechea_stare.get("downloaded", True),
            "Tags_extracted": vechea_stare.get("Tags_extracted", False),
            "processed": vechea_stare.get("processed", False)
        }

        for k, v in vechea_stare.items():
            if k not in master_index["fisiere"][nume_master]:
                master_index["fisiere"][nume_master][k] = v

    master_index["total_fisiere"] = len(master_index["fisiere"])
