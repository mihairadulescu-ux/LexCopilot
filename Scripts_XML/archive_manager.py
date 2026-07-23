import os
import sys
import tarfile
import io

# Standard logare live
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def creeaza_sau_actualizeaza_arhiva_an(an, lista_fisiere_xml_locale, cale_iesire_tar_gz):
    """
    Împachetează sau adaugă o listă de fișiere XML locale într-o arhivă .tar.gz dedicată anului respectiv.
    """
    print(f"📦 [ARCHIVE MANAGER] Se procesează arhiva pentru anul {an} ({len(lista_fisiere_xml_locale)} fișiere)...", flush=True)
    
    # Deschidem arhiva în modul de scriere cu compresie GZIP
    with tarfile.open(cale_iesire_tar_gz, "w:gz") as tar:
        for cale_fisier in lista_fisiere_xml_locale:
            nume_fisier = os.path.basename(cale_fisier)
            tar.add(cale_fisier, arcname=nume_fisier)
            
    dimensiune_mb = os.path.getsize(cale_iesire_tar_gz) / (1024 * 1024)
    print(f"✅ [ARCHIVE MANAGER] Arhiva {os.path.basename(cale_iesire_tar_gz)} a fost creată cu succes! Dimensiune: {dimensiune_mb:.2f} MB", flush=True)
    return cale_iesire_tar_gz

if __name__ == "__main__":
    print("🔧 Engine Archiver pregătit. Folosiți ca modul în pipeline-ul principal.", flush=True)
