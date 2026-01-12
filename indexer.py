import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ===============================
# CONFIGURACIÓN
# ===============================

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents.readonly"
]

FOLDER_NAME = "CHATBOT INTRANET"
OUTPUT_FILE = "data.json"

# ===============================
# AUTENTICACIÓN
# ===============================

service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
credentials = service_account.Credentials.from_service_account_info(
    service_account_info, scopes=SCOPES
)

drive_service = build("drive", "v3", credentials=credentials)
sheets_service = build("sheets", "v4", credentials=credentials)
docs_service = build("docs", "v1", credentials=credentials)

# ===============================
# UTILIDADES
# ===============================

def get_folder_id_by_name(name):
    results = drive_service.files().list(
        q=f"name='{name}' and mimeType='application/vnd.google-apps.folder'",
        fields="files(id, name)"
    ).execute()

    files = results.get("files", [])
    if not files:
        raise Exception(f"No se encontró la carpeta {name}")
    return files[0]["id"]


def list_files_in_folder(folder_id):
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents",
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get("files", [])

# ===============================
# PARSER DE GOOGLE SHEETS
# ===============================

def parse_sheet(file_id):
    result = []

    sheet = sheets_service.spreadsheets().values().get(
        spreadsheetId=file_id,
        range="A:Z"
    ).execute()

    rows = sheet.get("values", [])
    if len(rows) < 2:
        return result

    headers = [h.strip().lower() for h in rows[0]]

    def col(name):
        return headers.index(name) if name in headers else None

    idx_fecha = col("fecha")
    idx_titulo = col("título")
    idx_categoria = col("categoría web")
    idx_tipo = col("tipo")
    idx_autor = col("autor")
    idx_link = col("link")

    for row in rows[1:]:
        def val(i):
            return row[i].strip() if i is not None and i < len(row) else None

        fecha = val(idx_fecha)
        titulo = val(idx_titulo)

        if not fecha and not titulo:
            continue

        result.append({
            "tipo": "sheet",
            "fecha": fecha,
            "titulo": titulo,
            "seccion": val(idx_categoria),
            "autor": val(idx_autor),
            "url": val(idx_link),
            "clasificacion": val(idx_tipo),
            "id": f"{fecha}-{titulo}" if titulo else fecha
        })

    return result


# ===============================
# PARSER DE GOOGLE DOCS
# ===============================

def parse_doc(file_id):
    result = []

    doc = docs_service.documents().get(documentId=file_id).execute()
    content = doc.get("body", {}).get("content", [])

    texto = ""
    for element in content:
        if "paragraph" in element:
            for run in element["paragraph"].get("elements", []):
                texto += run.get("textRun", {}).get("content", "")

    bloques = texto.split("\n\n")

    for bloque in bloques:
        bloque = bloque.strip()
        if len(bloque) < 50:
            continue

        result.append({
            "tipo": "doc",
            "texto": bloque
        })

    return result

# ===============================
# PROCESO PRINCIPAL
# ===============================

def main():
    data = []

    folder_id = get_folder_id_by_name(FOLDER_NAME)
    files = list_files_in_folder(folder_id)

    print("Archivos encontrados:")
    for f in files:
        print(f"- {f['name']} ({f['mimeType']})")

        if f["mimeType"] == "application/vnd.google-apps.spreadsheet":
            data.extend(parse_sheet(f["id"]))

        elif f["mimeType"] == "application/vnd.google-apps.document":
            data.extend(parse_doc(f["id"]))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✔ Indexación completa: {len(data)} registros generados")
    print("✔ data.json generado y disponible en el servidor")

# ===============================
# EJECUCIÓN
# ===============================

if __name__ == "__main__":
    main()
