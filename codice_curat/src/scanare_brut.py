import re
from datetime import datetime

class RawMetadataExtractor:
    def __init__(self, text: str):
        self.text = text
        self.metadata = {}

    def extract_all(self) -> dict:
        """Rulează toate extractoarele de metadate brute."""
        self.metadata["emitent_brut"] = self.extract_raw_emitter()
        self.metadata["tip_act_brut"] = self.extract_raw_act_type()
        self.metadata["date_calendaristice_brute"] = self.extract_raw_dates()
        self.metadata["structura_articole_brute"] = self.extract_raw_structure()
        self.metadata["formule_modificare_brute"] = self.extract_raw_modification_formulas()
        return self.metadata

    def extract_raw_emitter(self) -> str:
        """
        Caută emitentul în primele linii ale documentului.
        De obicei apare după 'EMITENT' sau la începutul actului.
        """
        # Căutăm tipare precum "EMITENT: <Nume>" sau "EMITENT <Nume>" în primele 1000 de caractere
        header_area = self.text[:1000]
        match = re.search(r'(?:EMITENT|EMITENTUL)[:\s]+([^\n\r]+)', header_area, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Fallback: primele linii dacă nu există cuvântul cheie "EMITENT"
        lines = [line.strip() for line in header_area.split('\n') if line.strip()]
        for line in lines[:5]:
            if any(kw in line.upper() for kw in ["MINISTERUL", "GUVERNUL", "PARLAMENTUL", "AUTORITATEA", "AGENȚIA", "AGENCIA", "CURTEA"]):
                return line
        return "Nespecificat/Nedetectat"

    def extract_raw_act_type(self) -> str:
        """Extractează tipul brut de act (Lege, OUG, Ordin, Decizie etc.)."""
        # Căutăm la începutul documentului cuvinte cheie specifice
        header_area = self.text[:500]
        act_types_patterns = [
            r'\bLEGE\b', r'\bORDONANȚĂ DE URGENȚĂ\b', r'\bORDONANTA DE URGENTA\b', 
            r'\bORDONANȚĂ\b', r'\bORDONANTA\b', r'\bHOTĂRÂRE\b', r'\bHOTARARE\b', 
            r'\bORDIN\b', r'\bDECIZIE\b', r'\bDECRET\b', r'\bINSTRUCTIUNI\b', r'\bINSTRUCȚIUNI\b'
        ]
        
        for pattern in act_types_patterns:
            match = re.search(pattern, header_area, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return "Tip Act Nedetectat"

    def extract_raw_dates(self) -> dict:
        """
        Extrage datele calendaristice brute menționate în contextul publicării
        sau adoptării actului (ex: 'publicat în Monitorul Oficial din 15 iulie 2026').
        """
        # Căutăm structuri de date românești (ex: 15 iulie 2026 sau 15.07.2026)
        date_pattern = r'\b(\d{1,2}\s+(?:ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie|ian|feb|mar|apr|mai|iun|iul|aug|sept|oct|nov|dec)\s+\d{4})|\b(\d{1,2}[\./\-]\d{1,2}[\./\-]\d{4})\b'
        
        dates_found = []
        for match in re.finditer(date_pattern, self.text, re.IGNORECASE):
            dates_found.append(match.group(0))
            
        return {
            "toate_datele_gasite": list(set(dates_found))[:5], # primele 5 date brute găsite
            "context_data_publicare": self._get_context("Monitorul Oficial", 100)
        }

    def extract_raw_structure(self) -> list:
        """
        Identifică structura de capitole, articole și alineate în formă brută.
        """
        structure = []
        # Căutăm "Art. 1", "Articolul 1", "Capitolul I", "Sectiunea 1" etc.
        patterns = {
            "CAPITOL": r'\b(?:CAPITOLUL|CAPITOL)\s+([IVXLCDM\d]+)',
            "SECTIUNE": r'\b(?:SECȚIUNEA|SECTIUNEA|SECȚIUNE|SECTIUNE)\s+(\d+|[IVXLCDM]+)',
            "ARTICOL": r'\b(?:ARTICOLUL|ART\.)\s+(\d+)'
        }
        
        for unit_type, pattern in patterns.items():
            matches = re.findall(pattern, self.text, re.IGNORECASE)
            if matches:
                structure.append(f"{unit_type} brute găsite: {list(set(matches))[:10]}") # limităm la primele 10 pentru vizualizare
                
        return structure

    def extract_raw_modification_formulas(self) -> list:
        """
        Extrage paragrafele brute care conțin formule tipice de modificare, 
        abrogare, completare sau prorogare.
        """
        formulas = []
        keywords = [
            r'se abrogă', r'se abroga', 
            r'se modifică', r'se modifica', 
            r'se completează', r'se completeaza', 
            r'se suspendă', r'se suspenda', 
            r'se prorogă', r'se proroga'
        ]
        
        # Împărțim textul în propoziții/fraze brute pentru a izola contextul
        sentences = re.split(r'[\.\n]', self.text)
        for sentence in sentences:
            sentence_clean = sentence.strip()
            if any(re.search(kw, sentence_clean, re.IGNORECASE) for kw in keywords):
                if len(sentence_clean) > 10 and sentence_clean not in formulas:
                    formulas.append(sentence_clean[:150] + "...") # luăm doar începutul frazei brute
                    
        return formulas[:10] # limităm la primele 10 formule brute detectate

    def _get_context(self, keyword: str, chars_around: int) -> str:
        """Funcție ajutătoare pentru a extrage contextul din jurul unui cuvânt cheie."""
        idx = self.text.lower().find(keyword.lower())
        if idx != -1:
            start = max(0, idx - chars_around)
            end = min(len(self.text), idx + len(keyword) + chars_around)
            return "..." + self.text[start:end].replace('\n', ' ').strip() + "..."
        return "Nu s-a găsit context"

# --- EXEMPLU DE RULARE PE TEXT BRUT ---
if __name__ == "__main__":
    exemplu_text_lege = """
    MONITORUL OFICIAL AL ROMÂNIEI, PARTEA I, Nr. 542 din 15 iulie 2026.
    EMITENT: MINISTERUL FINANȚELOR
    ORDIN pentru modificarea unor norme metodologice.
    
    Având în vedere referatul de aprobare...
    CAPITOLUL I: Dispoziții generale.
    Art. 1. - Prezentele norme se aplică instituțiilor publice.
    Art. 2. - La data intrării în vigoare a prezentului ordin, se abrogă Articolul 5 din Ordinul nr. 120/2021.
    Art. 3. - Articolul 10 din Legea nr. 227/2015 se modifică și va avea următorul cuprins...
    """
    
    extractor = RawMetadataExtractor(exemplu_text_lege)
    rezultate_brute = extractor.extract_all()
    
    import json
    print(json.dumps(rezultate_brute, indent=4, ensure_ascii=False))
