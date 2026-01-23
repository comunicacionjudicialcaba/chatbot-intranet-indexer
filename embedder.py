import json
import os
import time
import numpy as np
import requests

INPUT = "chunks.json"
VECTORS_OUT = "embeddings.npy"
META_OUT = "meta.json"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

MODEL = "text-embedding-3-small"


def get_embedding(text):
    r = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "input": text,
        },
        timeout=60,
    )

    if r.status_code != 200:
        print("❌ Error OpenAI:", r.status_code, r.text)
        raise Exception("Fallo al generar embedding")

    data = r.json()
    return data["data"][0]["embedding"]


with open(INPUT, "r", encoding="utf-8") as f:
    chunks = json.load(f)

print("Chunks cargados:", len(chunks))

vectors = []
meta = []

for i, ch in enumerate(chunks):
    text = ch.get("texto", "").strip()

    if not text:
        continue

    emb = get_embedding(text)
    vectors.append(emb)

    meta.append({
        "id": ch.get("id"),
        "url": ch.get("url"),
        "titulo": ch.get("titulo"),
        "fecha": ch.get("fecha"),
        "tipo": ch.get("tipo"),
        "seccion": ch.get("seccion"),
        "texto": text,
    })

    if i % 50 == 0:
        print("Procesados:", i)
        time.sleep(0.3)

np.save(VECTORS_OUT, np.array(vectors, dtype="float32"))

with open(META_OUT, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print("✔ Embeddings generados:", len(vectors))
print("✔ Meta guardada con texto:", len(meta))
