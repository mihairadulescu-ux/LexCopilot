name: "🚀 Descărcare Legislație Paralelă XML"

on:
  workflow_dispatch: # Pornire manuală din GitHub Actions
  schedule:
    - cron: '0 1 * * *' # Rulează automat în fiecare noapte la ora 01:00 AM UTC

jobs:
  # 1. JOBUL DE DICTIONARE: Rulează o singură dată la început pentru a actualiza Emitenții și Tip Acte
  update_dictionaries:
    name: "📊 Actualizare Dicționare Metadate"
    runs-on: ubuntu-latest
    steps:
      - name: Descărcare cod din repository
        uses: actions/checkout@v4

      - name: Configurare mediu Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Instalare dependențe
        run: |
          python -m pip install --upgrade pip
          pip install zeep google-api-python-client google-auth requests

      - name: Actualizează Dicționare în Drive
        env:
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
          METADATA_FOLDER_ID: ${{ vars.METADATA_FOLDER_ID }} # Luat din variabilele globale GitHub
          PYTHONUNBUFFERED: "1"
        run: |
          python -u Scripts_XML/download_XML_dictionaries.py

  # 2. JOBUL DE MATRICE: Descarcă paginile XML brute în paralel pe intervale de ani
  download_xml:
    name: "🚀 XML Segment: ${{ matrix.nume }}"
    needs: update_dictionaries # Pornește doar DUPĂ ce dicționarele s-au actualizat cu succes
    runs-on: ubuntu-latest
    
    strategy:
      fail-fast: false # Dacă un segment dă eroare, celelalte continuă să ruleze!
      matrix:
        include:
          # Istoric (1990 - 1999)
          - nume: "1990 - 1991"
            start: 1990
            end: 1991
          - nume: "1992 - 1993"
            start: 1992
            end: 1993
          - nume: "1994 - 1995"
            start: 1994
            end: 1995
          - nume: "1996 - 1997"
            start: 1996
            end: 1997
          - nume: "1998 - 1999"
            start: 1998
            end: 1999
          # Era Nouă (2000 - 2026)
          - nume: "2000 - 2002"
            start: 2000
            end: 2002
          - nume: "2003 - 2004"
            start: 2003
            end: 2004
          - nume: "2005 - 2006"
            start: 2005
            end: 2006
          - nume: "2007 - 2008"
            start: 2007
            end: 2008
          - nume: "2009 - 2010"
            start: 2009
            end: 2010
          - nume: "2011 - 2012"
            start: 2011
            end: 2012
          - nume: "2013 - 2014"
            start: 2013
            end: 2014
          - nume: "2015 - 2016"
            start: 2015
            end: 2016
          - nume: "2017 - 2018"
            start: 2017
            end: 2018
          - nume: "2019 - 2020"
            start: 2019
            end: 2020
          - nume: "2021 - 2022"
            start: 2021
            end: 2022
          - nume: "2023 - 2024"
            start: 2023
            end: 2024
          - nume: "2025 - 2026"
            start: 2025
            end: 2026

    steps:
      - name: Descărcare cod din repository
        uses: actions/checkout@v4

      - name: Configurare mediu Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Instalare dependențe
        run: |
          python -m pip install --upgrade pip
          pip install lxml zeep google-api-python-client google-auth requests

      - name: Executare Sincronizare XML
        env:
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
          DRIVE_FOLDER_XML: ${{ vars.DRIVE_FOLDER_XML }} # Luat din variabilele globale GitHub
          START_YEAR: ${{ matrix.start }}
          END_YEAR: ${{ matrix.end }}
          PYTHONUNBUFFERED: "1"
        run: |
          python -u Scripts_XML/download_XML.py ${{ matrix.start }} ${{ matrix.end }}
