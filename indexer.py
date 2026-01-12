import os
import json
import re
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# =========================
# CONFIG
# =========================
FOLDER_NAME = "CHATBOT INTRANET"
OUTPUT_FILE = "data.json"

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
]

# =========================
# AUTH
# =========================
creds = service_account.Credentials.from_service_account_info(
    json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
    scopes=SCOPES,
)

drive = build("drive", "v3", credentials=creds)
sheets = build("sheets", "v4", credentials=creds)
docs = build("docs", "v1", credentials=creds)

# =========================
# HELPERS
# =========================
def normalize(text):
    return re.sub(r"\s+", " ", text.strip().lower())

def find_root_folder():
    res = drive.files().list(
        q=f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder'",
        fields="files(id,name)"
    ).execute()
    return res["files"][0]["id"]

def list_files(folder_id):
    res = drive.files().list(
        q=f"'{folder_id}' in parents",
        fields="files(id,name,mimeType)"
    ).execute()
    return res["files"]

def parse_doc(file_id):
    doc = docs.documents().get(documentId=file_id).execute()
    text = ""
    for el in doc.get("body", {}).get("content", []):
        if "paragraph" in el:
            for e in el["paragraph"].get("elements", []):
                if "textRun" in e:
                    text += e["textRun"]["content"]

    blocks = re.split(r"\n(?=[A-ZÁÉÍÓÚÑa-záéíóúñ]+ \d{2} de )", text)
    items = []

    for block in blocks:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if len(lines) < 3:
            continue

        fecha = lines[0]
        titulo = lines[1]
        body = "\n".join(lines[2:])

        url_match = re.search(r"https?://\S+", block)
        url = url_match.group(0) if url_match else None

        uid = url or f"{fecha}-{normalize(titulo)}"

        items.append({
            "id": uid,
            "fecha": fecha,
            "titulo": titulo,
            "texto": body,
            "url": url,
            "tipo": "doc"
        })

    return items

def normalize(text):
    if not text:
        return ""
    return text.strip().lower().replace(" ", "").replace("_", "")


def parse_sheet(file_id):
    result = []

    sheet = sheets_service.spreadsheets().values().get(
        spreadsheetId=file_id,
        range="A:Z"
    ).execute()

    rows = sheet.get("values", [])
    if not rows:
        return result

    headers = rows[0]
    header_map = {}

    for idx, h in enumerate(headers):
        header_map[normalize(h)] = idx

    def get(col_name, row):
        key = normalize(col_name)
        idx = header_map.get(key)
        if idx is not None and idx < len(row):
            return row[idx]
        return None

    for row in rows[1:]:
        fecha = get("fecha", row)
        titulo = get("titulo", row)
        seccion = get("seccion", row)
        autor = get("autor", row)
        url = get("url", row)

        if not (fecha or titulo):
            continue

        result.append({
            "tipo": "sheet",
            "fecha": fecha,
            "titulo": titulo,
            "seccion": seccion,
            "autor": autor,
            "url": url,
            "id": f"{fecha}-{titulo}" if titulo else fecha
        })

    return result


# =========================
# MAIN
# =========================
folder_id = find_root_folder()
files = list_files(folder_id)

print("Archivos encontrados:")
for f in files:
    print(f"- {f['name']} ({f['mimeType']})")

data = []

for f in files:
    if f["mimeType"] == "application/vnd.google-apps.document":
        data.extend(parse_doc(f["id"]))

    if f["mimeType"] == "application/vnd.google-apps.spreadsheet":
        data.extend(parse_sheet(f["id"]))

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\n✔ Indexación completa: {len(data)} registros generados")

print("✔ Indexación completa: data.json generado y disponible en el servidor")

