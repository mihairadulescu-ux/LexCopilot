import os
import re
import csv
from collections import Counter
import xml.etree.ElementTree as ET
from google.colab import drive

# 1. Montăm Google Drive pentru a avea acces la foldere
drive.mount('/content/drive')

# Definim ID-urile folderelor din structura Drive-ului tău
# Notă: În Google Colab, cel mai simplu mod este să folosești calea fizică 
# din "My Drive" după ce ai dat "Add shortcut to Drive" pentru folderele partajate,
# sau să folosești API-ul Google Drive direct.
# Presupunem că folderele sunt mapate în Drive-ul tău:

FORDER_SURSA_XML = "/content/drive/MyDrive/1O9c1S2QgRk85DrfigMsneRiQ2E7bq-0m"  # Folderul cu XML brute
FOLDER_METADATE = "/content/drive/MyDrive/1Cpxs20QAtAPw_RIUsOOecJON9hHPlBXf"   # Folderul destinație pentru CSV-uri

# Inițializăm countere pentru a vedea și frecvența (ajută la identificarea anomaliilor)
emitenti_counter = Counter()
tipuri_acte_counter = Counter()

def curata_text_brut(text):
    if not text:
        return ""
    # Eliminăm spațiile multiple, tab-urile și newline-urile interne
    text_curat = re.sub(r'\s+', ' ', text).strip()
    return text_curat

def proceseaza_xml(cale_fisier):
    try:
        # Folosim un parser flexibil care ignoră erorile mici de XML (folositor la fișiere brute)
        parser = ET.XMLParser(encoding="utf-8")
        tree = ET.parse(cale_fisier, parser=parser)
        root = tree.getroot()
        
        # Căutăm tag-urile indiferent de namespace-ul XML (folosind local-name)
        emitent_elem = root.find(".//*{http://schemas.datacontract.org/2004/07/Legis.Sg.Doc}Emitent") or root.find(".//Emitent")
        tip_act_elem = root.find(".//*{http://schemas.datacontract.org/2004/07/Legis.Sg.Doc}TipAct") or root.find(".//TipAct")
        
        if emitent_elem is not None and emitent_elem.text:
            emitent_curat = curata_text_brut(emitent_elem.text)
            if emitent_curat:
                emitenti_counter[emitent_curat] += 1
                
        if tip_act_elem is not None and tip_act_elem.text:
            tip_act_curat = curata_text_brut(tip_act_elem.text)
            if tip_act_curat:
                tipuri_acte_counter[tip_act_curat] += 1
                
    except Exception as e:
        print(f"Eroare la procesarea fișierului {os.path.basename(cale_fisier)}: {e}")

# Scanăm folderul sursă
print("Începe scanarea XML-urilor brute...")
for root_dir, _, files in os.walk(FORDER_SURSA_XML):
    for file in files:
        if file.endswith('.xml'):
            cale_completa = os.path.join(root_dir, file)
            proceseaza_xml(cale_completa)

# Asigurăm existența folderului destinație
os.makedirs(FOLDER_METADATE, exist_ok=True)

# Salvare Emitenți în CSV
cale_emitenti_csv = os.path.join(FOLDER_METADATE, "emitenti_brut.csv")
with open(cale_emitenti_csv, mode='w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["Emitent_Original", "Aparitii"])
    for emitent, count in emitenti_counter.most_common():
        writer.writerow([emitent, count])

# Salvare Tipuri Acte în CSV
cale_tipuri_csv = os.path.join(FOLDER_METADATE, "tipuri_acte_brut.csv")
with open(cale_tipuri_csv, mode='w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["TipAct_Original", "Aparitii"])
    for tip_act, count in tipuri_acte_counter.most_common():
        writer.writerow([tip_act, count])

print(f"Procesare finalizată cu succes!")
print(f"Fișier emitenți salvat în: {cale_emitenti_csv} (Unici detectați: {len(emitenti_counter)})")
print(f"Fișier tipuri acte salvat în: {cale_tipuri_csv} (Unici detectați: {len(tipuri_acte_counter)})")
