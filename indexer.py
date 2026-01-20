import os
import json
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build

# =========================
# CONFIG
# =========================

FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
OUTPUT_FILE = "data.json"

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

# =========================
# AUTH
# =========================

creds = service_account.Credentials.from_service_account_info(
    json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
    scopes=SCOPES,
)

drive_service = build("drive", "v3", credentials=creds)
docs_service = build("docs", "v1", credentials=creds)
sheets_service = build("sheets", "v4", credentials=creds)

# =========================
# HELPERS
# =========================

def clean_text(t):
    t = re.sub(r"\s+", " ", t)
    return t.strip()


# =========================
# PARSE DOC
# =========================

def parse_doc(doc_id):
    doc = docs_service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    full_text = ""

    for el in content:
        if "paragraph" in el:
            for e in el["paragraph"].get("elements", []):
                if "textRun" in e:
                    full_text += e["textRun"].get("content", "")

    full_text = clean_text(full_text)

    # intentar detectar URL al final
    url_match = re.search(r"https?://\S+", full_text)
    url = url_match.group(0) if url_match else None

    # heurísticas básicas
    fecha_match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", full_text)
    fecha = fecha_match.group(1) if fecha_match else None

    titulo = doc.get("title")

    return [{
        "tipo": "doc",
        "titulo": titulo,
        "fecha": fecha,
        "autor": None,
        "seccion": None,
        "url": url,
        "texto": full_text
    }]


# =========================
# PARSE SHEET
# =========================

def parse_sheet(sheet_id):
    sheet = sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    sheet_name = sheet["sheets"][0]["properties"]["title"]

    values = sheets_service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=sheet_name
    ).execute().get("values", [])

    if not values:
        return []

    headers = [h.strip().lower() for h in values[0]]

    def idx(name):
        for i, h in enumerate(headers):
            if name in h:
                return i
        return None

    i_fecha = idx("fecha")
    i_titulo = idx("título") or idx("titulo")
    i_autor = idx("autor")
    i_seccion = idx("categoría") or idx("sección") or idx("seccion")
    i_url = idx("link") or idx("url")

    rows = []

    for r in values[1:]:
        rows.append({
            "tipo": "sheet",
            "titulo": r[i_titulo] if i_titulo is not None and i_titulo < len(r) else None,
            "fecha": r[i_fecha] if i_fecha is not None and i_fecha < len(r) else None,
            "autor": r[i_autor] if i_autor is not None and i_autor < len(r) else None,
            "seccion": r[i_seccion] if i_seccion is not None and i_seccion < len(r) else None,
            "url": r[i_url] if i_url is not None and i_url < len(r) else None,
            "texto": None
        })

    return rows


# =========================
# MAIN
# =========================

def main():
    results = drive_service.files().list(
        q=f"'{FOLDER_ID}' in parents and trashed=false",
        fields="files(id, name, mimeType)"
    ).execute()

    files = results.get("files", [])

    print("Archivos encontrados:")
    for f in files:
        print("-", f["name"], f["mimeType"])

    data = []

    for f in files:
        if f["mimeType"] == "application/vnd.google-apps.document":
            data.extend(parse_doc(f["id"]))

        if f["mimeType"] == "application/vnd.google-apps.spreadsheet":
            data.extend(parse_sheet(f["id"]))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✔ Indexación completa: {len(data)} registros generados")
    print("✔ data.json generado con texto completo de Docs")


if __name__ == "__main__":
    main()
