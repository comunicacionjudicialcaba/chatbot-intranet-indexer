import json
import math

INPUT = "data.json"
OUTPUT = "chunks.json"

MAX_CHARS = 1200      # aprox 300 tokens
MIN_CHARS = 200

# ------------------------
# UTILS
# ------------------------

def split_paragraphs(text):
    parts = []
    buf = []

    for line in text.split("\n"):
        if line.strip():
            buf.append(line.strip())
        else:
            if buf:
                parts.append(" ".join(buf))
                buf = []
    if buf:
        parts.append(" ".join(buf))

    return parts


def group_paragraphs(paragraphs):
    chunks = []
    current = ""

    for p in paragraphs:
        if len(current) + len(p) < MAX_CHARS:
            current += ("\n" if current else "") + p
        else:
            if len(current) >= MIN_CHARS:
                chunks.append(current.strip())
                current = p
            else:
                current += "\n" + p

    if len(current) >= MIN_CHARS:
        chunks.append(current.strip())

    return chunks

# ------------------------
# MAIN
# ------------------------

with open(INPUT, "r", encoding="utf-8") as f:
    data = json.load(f)

all_chunks = []

for idx, item in enumerate(data):
    texto = (item.get("texto") or "").strip()
    if len(texto) < 80:
        continue

    paragraphs = split_paragraphs(texto)
    parts = group_paragraphs(paragraphs)

    for i, part in enumerate(parts):
        all_chunks.append({
            "id": f"{item.get('url','item-'+str(idx))}#chunk-{i}",
            "url": item.get("url"),
            "titulo": item.get("titulo"),
            "fecha": item.get("fecha"),
            "fecha_iso": item.get("fecha_iso"),
            "anio": item.get("anio"),
            "mes": item.get("mes"),
            "tipo": item.get("tipo"),
            "seccion": item.get("seccion"),
            "texto": part
        })

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(all_chunks, f, ensure_ascii=False, indent=2)

print("✔ Chunks generados:", len(all_chunks))
