from flask import Flask, jsonify, request, render_template
import json, os
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

with open("meta.json", encoding="utf-8") as f:
    metadata = json.load(f)

norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
embeddings_norm = embeddings / norms

print(f"✅ Embeddings cargados: {embeddings_norm.shape}")

# ------------------------
# SEMANTIC SEARCH
# ------------------------

def semantic_search(query_embedding, top_k=15):
    q = query_embedding / np.linalg.norm(query_embedding)
    sims = np.dot(embeddings_norm, q)
    top_idx = np.argsort(sims)[-top_k:][::-1]
    results = [metadata[i] for i in top_idx]
    scores = [float(sims[i]) for i in top_idx]
    return results, scores

# ------------------------
# HELPERS
# ------------------------

def parse_date(fecha):
    try:
        return datetime.strptime(fecha.strip(), "%d/%m/%Y")
    except:
        return datetime.min

def safe(v):
    return v if v not in [None, "", "null"] else ""

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
            f"Tipo: {d.get('tipo','')}\n"
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
# SEARCH (clásico)
# ------------------------

@app.route("/search")
def search():
    q = request.args.get("q", "").lower().strip()
    year = request.args.get("year", "").strip()

    res = []

    for n in DATA:
        titulo = safe(n.get("titulo", "")).lower()
        texto = safe(n.get("texto", "")).lower()
        fecha = safe(n.get("fecha", ""))

        fulltext = f"{titulo} {texto}"

        if q and q not in fulltext:
            continue

        if year and not fecha.endswith(year):
            continue

        res.append(n)

    res.sort(key=lambda x: parse_date(x.get("fecha", "")), reverse=True)
    return jsonify(res[:50])

# ------------------------
# CHAT (RAG)
# ------------------------

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()

    question = (
        data.get("message")
        or data.get("question")
        or data.get("text")
        or ""
    ).strip()

    print("🔎 Pregunta:", question)

    if not question:
        return jsonify({"answer": "No recibí la pregunta."})

    # 1. embedding de la pregunta
    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    ).data[0].embedding

    # 2. búsqueda semántica
    chunks, scores = semantic_search(np.array(q_emb), top_k=15)

    # filtrar chunks con texto real
    chunks = [c for c in chunks if len(c.get("texto","")) > 300]

    print("📦 Chunks útiles:", len(chunks))

    if not chunks:
        return jsonify({"answer": "No encontré información relevante."})

    # 3. agrupar por documento
    docs = group_chunks_by_url(chunks)

    # ordenar por fecha desc (último plenario)
    docs.sort(key=lambda x: parse_date(x.get("fecha","")), reverse=True)
    main_doc = docs[:1]

    # 4. contexto
    context = build_context(main_doc)

    # 5. prompt de extracción
    system = (
        "Sos un asistente institucional del Poder Judicial de la CABA. "
        "Cuando el contexto sea un plenario, debés extraer y enumerar "
        "todas las decisiones, proyectos aprobados, informes y temas tratados. "
        "No resumas en palabras generales. Respondé en forma de lista detallada."
    )

    user_prompt = f"""
A partir del texto del plenario, enumerá todos los temas y decisiones tratadas.

Contexto:
{context}

Pregunta:
{question}
"""

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",  # o gpt-4o-mini
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    answer = completion.choices[0].message.content

    print("✅ RESPUESTA:", answer[:200])

    return jsonify({"answer": answer})

# ------------------------
# RUN
# ------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
