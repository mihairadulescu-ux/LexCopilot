Am actualizat Specificația Tehnică de Arhitectură (docs/ARCHITECTURE.md) pentru a integra explicit decizia noastră privind arhivarea .tar.gz pe ani pentru toate datele existente (indiferent dacă un an este complet închis sau doar parțial descărcat), precum și modul în care Indexul Master gestonează acești pointeri dinamici.Puteți salva versiunea actualizată direct în docs/ARCHITECTURE.md:📐 Specificație Tehnică de Arhitectură (Single Source of Truth)1. Viziune Generală & Infrastructură CloudSistemul este un pipeline distribuit automatizat (GitHub Actions) destinat preluării, indexării și stocării întregului corpus legislativ al României oferit de Portalul Legislativ (just.ro).Principii Fundamentale de Proiectare:ZERO Hardcoding (100% Dynamic Environment): Toate ID-urile de Shared Drive-uri, foldere tehnice, chei API și credențiale sunt preluate exclusiv din variabilele de mediu ale repozitoriului GitHub (Settings -> Secrets and variables -> Actions).Arhivare Universală Anuală .tar.gz (Anii Închiși și Parțiali):Toate fișierele XML existente pe discuri (indiferent de an, fie 1990, 2010 sau 2026, complet sau incomplet descărcat) sunt consolidate în arhive monolitice de tip brut_XML_{an}.tar.gz.Această decizie oferă o rată de compresie de peste 90%, eliberează cota de fișiere pe Google Drive și reduce numărul total de obiecte de la 300.000+ la doar ~35–40 de arhive.Dacă un an parțial descărcat primește fișiere noi ulterior, acestea sunt descărcate individual și pot fi adăugate dinamic/recomprimate în arhiva anului respectiv la runde periodice de consolidare.Master Index Centralizat Comprimat (index_xml.json.gz): Starea completă a tuturor fișierelor este menținută într-un singur punct de adevăr stocat ca JSON comprimat GZIP pe Google Drive. Indexul folosește pointeri transparenți (archive vs. individual) pentru a ști instant în ce arhivă sau fișier fizic se află fiecare pagină.Standard de Logare Live & Runtime Python 3.12+: Toate scripturile rulează sub Python 3.12+ cu flushing instantaneu al bufferului stdout (sys.stdout.reconfigure(line_buffering=True)).2. Configurația Mediului (Repository Variables & Secrets)Toate scripturile din Scripts_XML/ și Scripts_PDF/ citesc aceste variabile nativ la runtime. Este strict interzisă introducerea ID-urilor brute în cod.Nume VariabilăTipDescriere / FormatGDRIVE_SERVICE_ACCOUNT_JSONSecretJSON-ul complet al Service Account-ului Google Drive.FOLDERE_XML_RAWVariableID-urile celor 7 Shared Drive-uri XML, separate strict prin virgulă (ex: ID1,ID2,ID3,ID4,ID5,ID6,ID7).DRIVE_FOLDER_PDFVariableID-ul folderului/drive-ului dedicat fișierelor PDF (Monitorul Oficial Partea I).SOAP_SEARCH_ENDPOINTVariableEndpoint-ul WSDL Just.ro: [http://legislatie.just.ro/Ajust/SearchModel.svc?wsdl](http://legislatie.just.ro/Ajust/SearchModel.svc?wsdl)3. Protocolul SOAP / API Just.ro & Reguli de PreluareProtocolul WSDL & PaginareServiciul web expus de Just.ro returnează actele legislative structurate pe ani și pagini (100 rezultate per pagină).Regula de Oprire (Dynamic Sentinel): Procesarea unui an se oprește automat după detectarea a 20 de pagini goale consecutive returnate de API.Convenția Unică de Redenumire (Naming Standard)Pachete XML brute (înainte de arhivare): brut_XML_{an}_pag{pagina}.xmlArhive Anuale XML: brut_XML_{an}.tar.gzEdiții PDF Monitorul Oficial: MO_PI_{an}_{numar}{sufix}.pdf (ex: MO_PI_2024_1025a.pdf)4. Arhitectura de Indecși JSON & Pointeri HibriziToate operațiunile de verificare și citire interoghează în memorie dicționarul din index_xml.json.gz.Structura unei Intrări în Index (index_xml.json.gz)JSON{
  "brut_XML_1998_pag15.xml": {
    "an": 1998,
    "pagina": 15,
    "tip_stocare": "archive",
    "arhiva": "brut_XML_1998.tar.gz",
    "cale_interna": "pag15.xml",
    "drive_id": "1A2B3C4D5E6F7G8H..."
  },
  "brut_XML_2026_pag3.xml": {
    "an": 2026,
    "pagina": 3,
    "tip_stocare": "individual",
    "arhiva": null,
    "cale_interna": null,
    "drive_id": "9Z8Y7X6W5V4U3T2S..."
  }
}
Mecanismul de Rulare & Consolidation (Arhivare & Merge)Descărcare & Micro-Indecși: Preluările noi adaugă pagini libere pe Drive și scriu micro-indecși temporari (micro_index_{timestamp}.json).Merge & Purge: Scriptul de indexare îmbină micro-indecșii în index_xml.json.gz.Consolidare TAR.GZ (Archive Manager): Scanarea periodică ia fișierele libere brut_XML_{an}_pag*.xml, le împachetează în brut_XML_{an}.tar.gz pe Drive, actualizează pointerii în index (tip_stocare: "archive") și șterge fișierele libere duplicate de pe Drive.5. Structura Repozitoriului & Workspace XML (.system/project_workspace.xml)Pentru a oferi vizibilitate globală 100% și sincronizare instantanee între dezvoltator și asistentul AI, repozitoriul conține fișierul Master Workspace:Plaintext.
├── .github/
│   └── workflows/          <-- Toate workflow-urile GitHub Actions (Python 3.12+)
├── .system/
│   └── project_workspace.xml <-- Snapshot-ul XML integral al tuturor scripturilor din repo
├── docs/
│   └── ARCHITECTURE.md     <-- Această specificație tehnică
├── Scripts_XML/
│   ├── drive_config.py     <-- Preluare dinamică FOLDERE_XML_RAW (0 hardcoding)
│   ├── gdrive_wrapper.py   <-- Driver Google Drive API v3 (reîncercări, batching)
│   ├── download_xml.py     <-- Descărcare SOAP Just.ro & GZIP stream
│   ├── archive_manager.py  <-- Modul împachetare TAR.GZ per an (complet / parțial)
│   └── XML_INDEX_READER.py <-- Engine gestionare Master Index & Pointeri Arhivă
└── Scripts_PDF/
    ├── drive_config_pdf.py <-- Preluare dinamică DRIVE_FOLDER_PDF
    └── download_pdf.py     <-- Engine descărcare & verificare PDF-uri MO
6. Fluxul de Lucru cu Asistentul AI (Workspace Dynamic Flow)Plaintext  ┌─────────────────────────────────────────────────────────┐
  │         .system/project_workspace.xml                   │
  │  (Snapshot-ul tuturor scripturilor dintr-un singur loc) │
  └────────────────────────────┬────────────────────────────┘
                               │
       ┌───────────────────────┴───────────────────────┐
       ▼                                               ▼
[Încărcare XML în Chat]                   [Procesare & Refactorizare]
  ├─ Context global instant                  ├─ Modificare/Scriere cod nou
  └─ Verificare dependențe                   └─ Generare fișiere individuale + XML Master
