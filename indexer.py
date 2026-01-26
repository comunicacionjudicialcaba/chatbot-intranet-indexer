import os
import json
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build

# =========================
# CONFIG
# =========================

FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
OUTPUT_FILE = "data.json"

# =========================
# GOOGLE AUTH
# =========================

if not SERVICE_ACCOUNT_JSON:
    raise Exception("Falta GOOGLE_SERVICE_ACCOUNT_JSON")

creds_info = json.loads(SERVICE_ACCOUNT_JSON)

creds = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=[
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/documents.readonly",
    ],
)

drive_service = build("drive", "v3", credentials=creds)
sheets_service = build("sheets", "v4", credentials=creds)
docs_service = build("docs", "v1", credentials=creds)

# =========================
# FECHA NORMALIZADA
# =========================

MESES = {
    "enero":1, "febrero":2, "marzo":3, "abril":4, "mayo":5, "junio":6,
    "julio":7, "agosto":8, "septiembre":9, "octubre":10, "noviembre":11, "diciembre":12
}

def normalizar_fecha(fecha):
    if not fecha:
        return None, None, None

    f = fecha.strip().lower()

    # formato sheet: 17/12/2025
    try:
        d, m, y = f.split("/")
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}", int(y), int(m)
    except:
        pass

    # formato doc: miércoles 17 de diciembre de 2025
    for mes_txt, mes_num in MESES.items():
        if mes_txt in f:
            try:
                partes = f.split()
                dia = next(p for p in partes if p.isdigit())
                anio = int(partes[-1])
                return f"{anio}-{str(mes_num).zfill(2)}-{dia.zfill(2)}", anio, mes_num
            except:
                pass

    return None, None, None

# =========================
# DRIVE LIST
# =========================

def list_files():
    q = f"'{FOLDER_ID}' in parents and trashed = false"
    results = drive_service.files().list(
        q=q,
        fields="files(id, name, mimeType)",
        pageSize=1000,
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

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    data = []
    current = None

    fecha_re = re.compile(
        r"^(lunes|martes|miércoles|miercoles|jueves|viernes)?[, ]*\s*\d{1,2}\s+de\s+"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
        r"\s+de\s+\d{4}",
        re.I
    )

    for line in lines:

        # inicio de nueva nota
        if fecha_re.match(line):
            if current:
                data.append(current)

            current = {
                "fecha": line,
                "titulo": "",
                "texto": "",
                "url": "",
                "tipo": "doc",
            }
            continue

        if not current:
            continue

        # detectar URL en cualquier parte
        if "http" in line and "intranet.jusbaires.gob.ar" in line:
            current["url"] = line.strip()
            continue

        if not current["titulo"]:
            current["titulo"] = line
            continue

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
        range="A1:Z",
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
            "texto": "",
        }
        data.append(item)

    return data

# =========================
# MERGE BY URL + FECHA NORMALIZADA
# =========================

def merge_by_url(records):
    by_url = {}
    no_url = []

    for r in records:
        url = (r.get("url") or "").strip()
        if url:
            by_url.setdefault(url, []).append(r)
        else:
            no_url.append(r)

    merged = []

    for url, items in by_url.items():
        base = {"url": url, "texto": ""}

        for it in items:
            if it.get("tipo") == "sheet":
                for k, v in it.items():
                    if k != "texto":
                        base[k] = v
            else:
                base["texto"] += it.get("texto", "")
                base.setdefault("fecha", it.get("fecha"))
                base.setdefault("titulo", it.get("titulo"))
                base.setdefault("tipo", it.get("tipo"))

        merged.append(base)

    merged.extend(no_url)
    return merged


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

    print("Registros antes de merge:", len(data))

    data = merge_by_url(data)

    print("Registros después de merge:", len(data))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✔ Indexación completa: {len(data)} registros")

if __name__ == "__main__":
    main()
