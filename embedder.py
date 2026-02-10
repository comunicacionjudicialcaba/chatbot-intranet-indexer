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

# =========================================================
# OPENAI
# =========================================================

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

    return r.json()["data"][0]["embedding"]

# =========================================================
# LOAD CHUNKS
# =========================================================

with open(INPUT, "r", encoding="utf-8") as f:
    chunks = json.load(f)

print("📦 Chunks cargados:", len(chunks))

# =========================================================
# LOAD EXISTING EMBEDDINGS (SI EXISTEN)
# =========================================================

if os.path.exists(META_OUT) and os.path.exists(VECTORS_OUT):
    with open(META_OUT, "r", encoding="utf-8") as f:
        meta = json.load(f)
    vectors = np.load(VECTORS_OUT)
    print("📂 Embeddings existentes:", len(meta))
else:
    meta = []
    vectors = np.empty((0, 1536), dtype="float32")
    print("📂 No hay embeddings previos")

# =========================================================
# DETECTAR NUEVOS CHUNKS
# =========================================================

ids_existentes = {m["id"] for m in meta}

nuevos = [
    ch for ch in chunks
    if ch.get("id") not in ids_existentes
    and ch.get("texto", "").strip()
]

print("🆕 Chunks nuevos detectados:", len(nuevos))

if not nuevos:
    print("ℹ️ No hay nuevos embeddings para generar")
    exit(0)

# =========================================================
# GENERAR EMBEDDINGS SOLO PARA NUEVOS
# =========================================================

new_vectors = []
new_meta = []

for i, ch in enumerate(nuevos, start=1):
    text = ch["texto"].strip()

    emb = get_embedding(text)
    new_vectors.append(emb)

    new_meta.append({
        "id": ch.get("id"),
        "url": ch.get("url"),
        "titulo": ch.get("titulo"),
        "fecha": ch.get("fecha"),
        "tipo": ch.get("tipo"),
        "seccion": ch.get("seccion"),
        "texto": text,
    })

    if i % 50 == 0:
        print(f"Procesados nuevos: {i}")
        time.sleep(0.3)

# =========================================================
# APPEND + SAVE
# =========================================================

vectors = np.vstack([vectors, np.array(new_vectors, dtype="float32")])
meta.extend(new_meta)

np.save(VECTORS_OUT, vectors)

with open(META_OUT, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print("✅ Nuevos embeddings agregados:", len(new_vectors))
print("📊 Total embeddings:", len(meta))
