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

import re

def parse_doc(doc_id):
    doc = docs_service.documents().get(documentId=doc_id).execute()
    text = ""

    for el in doc.get("body", {}).get("content", []):
        if "paragraph" in el:
            for e in el["paragraph"].get("elements", []):
                if "textRun" in e:
                    text += e["textRun"].get("content", "")

    # normalizar saltos
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    data = []
    current = None

    fecha_re = re.compile(r"^(Lunes|Martes|Miércoles|Jueves|Viernes)\s+\d{1,2}")

    for line in lines:
        # nueva nota por fecha
        if fecha_re.match(line):
            if current:
                data.append(current)

            current = {
                "fecha": line,
                "titulo": "",
                "texto": "",
                "url": "",
                "tipo": "doc"
            }
            continue

        if not current:
            continue

        # URL
        if line.startswith("http"):
            current["url"] = line
            continue

        # título = primera línea después de fecha
        if not current["titulo"]:
            current["titulo"] = line
            continue

        # resto es cuerpo
        current["texto"] += line + "\n"

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

def merge_by_url(records):
    by_url = {}
    no_url = []

    for r in records:
        url = r.get("url", "").strip()
        if url:
            if url not in by_url:
                by_url[url] = []
            by_url[url].append(r)
        else:
            no_url.append(r)

    merged = []

    for url, items in by_url.items():
        base = {}

        for it in items:
            # prioriza datos del sheet
            if it.get("tipo") == "sheet":
                base.update(it)
            else:
                base.setdefault("fecha", it.get("fecha"))
                base.setdefault("titulo", it.get("titulo"))
                base.setdefault("texto", "")
                base["texto"] += it.get("texto", "")

        base["url"] = url
        merged.append(base)

    # agregar registros sin url (por si hay)
    merged.extend(no_url)

    return merged
    
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

    data = merge_by_url(data)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✔ Indexación completa: {len(data)} registros")
    
if __name__ == "__main__":
    main()
