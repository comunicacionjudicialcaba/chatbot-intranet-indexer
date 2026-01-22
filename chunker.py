import json, os, math

INPUT = "data.json"
OUTPUT = "chunks.json"

CHUNK_SIZE = 800   # caracteres
OVERLAP = 150      # solapamiento para no cortar ideas

def chunk_text(text, size, overlap):
    chunks = []
    start = 0
    n = len(text)

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

for item in data:
    texto = item.get("texto", "")
    if not texto or len(texto) < 50:
        continue

    parts = chunk_text(texto, CHUNK_SIZE, OVERLAP)

    for i, part in enumerate(parts):
        all_chunks.append({
            "id": f"{item.get('url','') }#{i}",
            "titulo": item.get("titulo"),
            "fecha": item.get("fecha"),
            "url": item.get("url"),
            "texto": part
        })

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(all_chunks, f, ensure_ascii=False, indent=2)

print("✔ Chunks generados:", len(all_chunks))
