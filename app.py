from flask import Flask, jsonify, request, render_template
import json
import os
from datetime import datetime
import numpy as np
from openai import OpenAI
from collections import defaultdict

# ------------------------
# INIT
# ------------------------

client = OpenAI()
app = Flask(__name__)

DATA_FILE = "data.json"

# ------------------------
# LOAD DATA (buscador clásico)
# ------------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

DATA = load_data()

# ------------------------
# LOAD EMBEDDINGS (RAG)
# ------------------------

print("🔄 Cargando embeddings...")

embeddings = np.load("embeddings.npy")

with open("meta.json", "r", encoding="utf-8") as f:
    metadata = json.load(f)

norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
embeddings_norm = embeddings / norms

print(f"✅ Embeddings cargados: {embeddings_norm.shape}")

# ------------------------
# SEMANTIC SEARCH
# ------------------------

def semantic_search(query_embedding, top_k=40):
    q = query_embedding / np.linalg.norm(query_embedding)
    sims = np.dot(embeddings_norm, q)
    top_idx = np.argsort(sims)[-top_k:][::-1]
    results = [metadata[i] for i in top_idx]
    scores = [float(sims[i]) for i in top_idx]
    return results, scores

# ------------------------
# HELPERS
# ------------------------

def parse_date_iso(fecha_iso):
    try:
        return datetime.strptime(fecha_iso, "%Y-%m-%d")
    except:
        return None

# ------------------------
# GROUP CHUNKS BY DOCUMENT
# ------------------------

def group_chunks_by_url(chunks):
    docs = defaultdict(list)
    for c in chunks:
        docs[c["url"]].append(c)

    grouped = []
    for url, parts in docs.items():
        text = "\n".join(p.get("texto", "") for p in parts)
        base = parts[0].copy()
        base["texto"] = text
        grouped.append(base)

    return grouped

# ------------------------
# BUILD CONTEXT
# ------------------------

def build_context(docs):
    partes = []
    for d in docs:
        partes.append(
            f"Título: {d.get('titulo','')}\n"
            f"Fecha: {d.get('fecha','')}\n"
            f"Texto completo:\n{d.get('texto','')}\n"
            f"URL: {d.get('url','')}\n"
        )
    return "\n---\n".join(partes)

# ------------------------
# ROUTES
# ------------------------

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/data")
def data():
    return jsonify(DATA)

# ------------------------
# CHAT
# ------------------------

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()

    question = (
        data.get("question")
        or data.get("message")
        or ""
    ).strip()

    print("🔎 Pregunta:", question)

    if not question:
        return jsonify({"answer": "No recibí la pregunta."})

    q_lower = question.lower()

    # ------------------------
    # 1. EMBEDDING
    # ------------------------

    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    ).data[0].embedding

    # ------------------------
    # 2. RETRIEVAL
    # ------------------------

    chunks, scores = semantic_search(np.array(q_emb), top_k=40)

    # solo chunks con texto
    chunks = [c for c in chunks if len(c.get("texto","")) > 300]

    # solo crónicas (no convocatorias)
    if "plenario" in q_lower:
        def es_cronica(t):
            t = t.lower()
            return not (
                t.startswith("convocatoria")
                or t.startswith("suspensión")
                or t.startswith("suspension")
            )
        chunks = [c for c in chunks if es_cronica(c.get("titulo",""))]

    # ------------------------
    # 3. FILTROS POR MES / ÚLTIMO
    # ------------------------

    # detectar mes en texto
    MESES = {
        "enero":1, "febrero":2, "marzo":3, "abril":4, "mayo":5, "junio":6,
        "julio":7, "agosto":8, "septiembre":9, "octubre":10, "noviembre":11, "diciembre":12
    }

    mes_pedido = None
    for k,v in MESES.items():
        if k in q_lower:
            mes_pedido = v

    if mes_pedido:
        chunks = [c for c in chunks if c.get("mes") == mes_pedido]

    # "último" → fecha más reciente
    if "último" in q_lower or "reciente" in q_lower:
        fechas = [parse_date_iso(c.get("fecha_iso")) for c in chunks if c.get("fecha_iso")]
        if fechas:
            max_fecha = max(fechas)
            chunks = [
                c for c in chunks
                if parse_date_iso(c.get("fecha_iso")) == max_fecha
            ]

    print("📦 Chunks finales:", len(chunks))
    for c in chunks[:5]:
        print(" -", c.get("titulo"), c.get("fecha_iso"))

    if not chunks:
        return jsonify({"answer": "No encontré información del período solicitado."})

    # ------------------------
    # 4. AGRUPAR POR DOCUMENTO
    # ------------------------

    docs = group_chunks_by_url(chunks)
    main_doc = docs[:1]

    # ------------------------
    # 5. CONTEXTO
    # ------------------------

    context = build_context(main_doc)

    # ------------------------
    # 6. PROMPT
    # ------------------------

    system = (
        "Sos un asistente institucional del Poder Judicial de la CABA. "
        "Debés enumerar decisiones y temas tratados en el plenario: "
        "proyectos aprobados, protocolos, reformas, convenios, informes "
        "y resoluciones de comisiones. No resumas en palabras generales."
    )

    user_prompt = f"""
Enumerá todos los temas tratados y decisiones tomadas en el plenario.

Contexto:
{context}

Pregunta:
{question}
"""

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    answer = completion.choices[0].message.content

    print("✅ RESPUESTA:", answer[:300])

    return jsonify({"answer": answer})

# ------------------------
# RUN
# ------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
