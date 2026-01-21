import os
import json
import subprocess
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# =========================
# CONFIG
# =========================

FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
OUTPUT_FILE = "data.json"

REPO_URL = "https://github.com/comunicacionjudicialcaba/chatbot-intranet-indexer.git"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# =========================
# GOOGLE AUTH
# =========================

creds_info = json.loads(SERVICE_ACCOUNT_JSON)

creds = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/documents.readonly"]
)

drive_service = build("drive", "v3", credentials=creds)
sheets_service = build("sheets", "v4", credentials=creds)
docs_service = build("docs", "v1", credentials=creds)

# =========================
# DRIVE LIST
# =========================

def list_files():
    q = f"'{FOLDER_ID}' in parents and trashed = false"
    results = drive_service.files().list(
        q=q,
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get("files", [])

# =========================
# PARSE DOC
# =========================

def parse_doc(doc_id):
    doc = docs_service.documents().get(documentId=doc_id).execute()
    text = ""

    for el in doc.get("body", {}).get("content", []):
        if "paragraph" in el:
            for e in el["paragraph"].get("elements", []):
                if "textRun" in e:
                    text += e["textRun"].get("content", "")

    blocks = [b.strip() for b in text.split("\n\n") if len(b.strip()) > 40]

    data = []
    current = None

    for block in blocks:
        # Detecta fecha tipo: "Lunes 30 de diciembre de 2025" o "03/01/2025"
        if block[:2].isdigit() and ("/" in block[:10] or "de" in block[:20]):
            if current:
                data.append(current)

            current = {
                "fecha": block.strip(),
                "titulo": "",
                "texto": "",
                "url": "",
                "tipo": "doc"
            }

        elif block.startswith("http"):
            if current:
                current["url"] = block.strip()

        elif current and not current["titulo"]:
            current["titulo"] = block.strip()

        elif current:
            current["texto"] += block + "\n"

    if current:
        data.append(current)

    return data


# =========================
# PARSE SHEET
# =========================

def parse_sheet(sheet_id):
    sheet = sheets_service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="A1:Z"
    ).execute()

    values = sheet.get("values", [])
    if not values:
        return []

    headers = [h.strip().lower() for h in values[0]]

    def idx(name):
        try:
            return headers.index(name)
        except:
            return None

    i_fecha = idx("fecha")
    i_titulo = idx("título") if "título" in headers else idx("titulo")
    i_autor = idx("autor")
    i_seccion = idx("categoría web") if "categoría web" in headers else idx("seccion")
    i_url = idx("link")

    data = []

    for row in values[1:]:
        item = {
            "tipo": "sheet",
            "fecha": row[i_fecha] if i_fecha is not None and i_fecha < len(row) else "",
            "titulo": row[i_titulo] if i_titulo is not None and i_titulo < len(row) else "",
            "autor": row[i_autor] if i_autor is not None and i_autor < len(row) else "",
            "seccion": row[i_seccion] if i_seccion is not None and i_seccion < len(row) else "",
            "url": row[i_url] if i_url is not None and i_url < len(row) else "",
            "texto": ""
        }
        data.append(item)

    return data

# =========================
# MAIN
# =========================

def main():
    files = list_files()

    print("Archivos encontrados:")
    for f in files:
        print("-", f["name"], f["mimeType"])

    data = []

    for f in files:
        if f["mimeType"] == "application/vnd.google-apps.document":
            data.extend(parse_doc(f["id"]))

        elif f["mimeType"] == "application/vnd.google-apps.spreadsheet":
            data.extend(parse_sheet(f["id"]))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✔ Indexación completa: {len(data)} registros")
    
if __name__ == "__main__":
    main()
