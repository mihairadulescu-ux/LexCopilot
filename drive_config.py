import os

# 1. Stocare XML - split dinamic din variabila DRIVE_FOLDER_XML
RAW_DRIVE_XML = os.getenv("DRIVE_FOLDER_XML", "")
if RAW_DRIVE_XML:
    FOLDERE_XML_IDS = [fid.strip() for fid in RAW_DRIVE_XML.split(",") if fid.strip()]
else:
    FOLDERE_XML_IDS = []

# 2. Indecși & Metadata
FOLDER_INDEX_ID = os.getenv("XML_STORAGE_INDEX", "")
FOLDER_TEMP_INDEXES_ID = os.getenv("TEMPORARY_XML_INDEXES", "")
METADATA_FOLDER_ID = os.getenv("METADATA_FOLDER_ID", "")

# 3. Stocare PDF
DRIVE_FOLDER_PDF = os.getenv("DRIVE_FOLDER_PDF", "")

# 4. Endpoint SOAP WSDL (preluat din env)
URL_WSDL = os.getenv("JUST_RO_WSDL_URL", "")


def get_file_params():
    return {
        "supportsAllDrives": True,
        "supportsTeamDrives": True,
    }


def get_list_params():
    return {
        "includeItemsFromAllDrives": True,
        "supportsAllDrives": True,
        "supportsTeamDrives": True,
    }
