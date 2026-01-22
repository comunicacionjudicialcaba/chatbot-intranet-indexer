import json

INPUT = "data.json"
OUTPUT = "chunks.json"

CHUNK_SIZE = 800
OVERLAP = 150


def chunk_text(text, size, overlap):
    chunks = []
    start = 0
    n = len(text)

    if n <= size:
        return [text.strip()]

    while start < n:
        end = start + size
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap
        if start < 0:
            start = 0

    return chunks


with open(INPUT, "r", encoding="utf-8") as f:
    data = json.load(f)

all_chunks = []

for idx, item in enumerate(data):
    titulo = item.get("titulo") or ""
    fecha = item.get("fecha") or ""
    seccion = item.get("seccion") or ""
    tipo = item.get("tipo") or ""
    url = item.get("url") or f"item-{idx}"

    texto = item.get("texto") or ""

    # -------- construir texto base para embeddings --------
    base_text = (
        f"Título: {titulo}\n"
        f"Fecha: {fecha}\n"
        f"Tipo: {tipo}\n"
        f"Sección: {seccion}\n\n"
        f"{texto}"
    ).strip()

    if len(base_text) < 40:
        continue

    parts = chunk_text(base_text, CHUNK_SIZE, OVERLAP)

    for i, part in enumerate(parts):
        all_chunks.append({
            "id": f"{url}#chunk-{i}",
            "url": url,
            "titulo": titulo,
            "fecha": fecha,
            "tipo": tipo,
            "seccion": seccion,
            "texto": part
        })

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(all_chunks, f, ensure_ascii=False, indent=2)

print("✔ Chunks generados:", len(all_chunks))
