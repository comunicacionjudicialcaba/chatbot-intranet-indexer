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

def semantic_search(query_embedding, top_k=50):
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

MESES = {
    "enero":1, "febrero":2, "marzo":3, "abril":4, "mayo":5, "junio":6,
    "julio":7, "agosto":8, "septiembre":9, "octubre":10, "noviembre":11, "diciembre":12
}

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
            f"TÍTULO: {d.get('titulo','')}\n"
            f"FECHA: {d.get('fecha','')}\n"
            f"TEXTO:\n{d.get('texto','')}\n"
            f"LINK: {d.get('url','')}\n"
        )
    return "\n---\n".join(partes)

# ------------------------
# RECALL TEMÁTICO DURO
# ------------------------

def recall_por_texto(palabras, metadata):
    results = []
    for c in metadata:
        blob = (c.get("titulo","") + " " + c.get("texto","")).lower()
        if any(p in blob for p in palabras):
            results.append(c)
    return results

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
    # DETECCIÓN DE INTENCIÓN
    # ------------------------

    es_plenario = "plenario" in q_lower
    es_frecuencia = (
        "frecuencia judicial" in q_lower
        or "podcast" in q_lower
        or "episodio" in q_lower
        or "episodios" in q_lower
    )

    # detectar mes
    mes_pedido = None
    for k, v in MESES.items():
        if k in q_lower:
            mes_pedido = v

    pedir_ultimo = "último" in q_lower or "ultimo" in q_lower or "reciente" in q_lower

    # ------------------------
    # 1. RETRIEVAL
    # ------------------------

    # ---- MODO PODCAST / SERIE ----
    if es_frecuencia:
        print("🎧 Modo Frecuencia Judicial (recall duro)")
        chunks = recall_por_texto(["frecuencia judicial"], metadata)

    # ---- MODO PLENARIO / GENERAL ----
    else:
        q_emb = client.embeddings.create(
            model="text-embedding-3-small",
            input=question
        ).data[0].embedding

        chunks, scores = semantic_search(np.array(q_emb), top_k=60)

        # filtrar convocatorias
        if es_plenario:
            def es_cronica(t):
                t = t.lower()
                return not (
                    t.startswith("convocatoria")
                    or t.startswith("suspensión")
                    or t.startswith("suspension")
                )
            chunks = [c for c in chunks if es_cronica(c.get("titulo",""))]

    # ------------------------
    # 2. FILTROS TEMPORALES
    # ------------------------

    if mes_pedido:
        chunks = [c for c in chunks if c.get("mes") == mes_pedido]

    if pedir_ultimo and chunks:
        fechas = [parse_date_iso(c.get("fecha_iso")) for c in chunks if c.get("fecha_iso")]
        if fechas:
            max_fecha = max(fechas)
            chunks = [
                c for c in chunks
                if parse_date_iso(c.get("fecha_iso")) == max_fecha
            ]

    if not chunks:
        return jsonify({"answer": "No encontré información para esa consulta."})

    # ------------------------
    # 3. AGRUPAR POR DOCUMENTO
    # ------------------------

    docs = group_chunks_by_url(chunks)

    # modo puntual → 1 doc
    if es_plenario and (mes_pedido or pedir_ultimo):
        docs = docs[:1]

    # modo temático → varios docs
    else:
        docs = docs[:15]

    # ------------------------
    # 4. CONTEXTO
    # ------------------------

    context = build_context(docs)

    # ------------------------
    # 5. PROMPT
    # ------------------------

    SYSTEM_PROMPT = """
Sos un asistente del Consejo de la Magistratura de la Ciudad Autónoma de Buenos Aires.
Respondés únicamente con la información incluida en el CONTEXTO provisto.

REGLAS:
- No inventes información que no esté en el texto.
- Si algo no se menciona, decí: "No se menciona en las notas".
- No mezcles información de documentos distintos.
- Usá solo el TEXTO, no infieras por el título.

PLENARIOS:
- Enumerá TODOS los puntos tratados.
- Incluí proyectos, protocolos, reformas, convenios, informes y comisiones.

SERIES / PODCAST / LISTADOS:
- Enumerá TODOS los ítems del contexto.
- Para cada uno indicá:
  • Título
  • Tema principal
  • Fecha si figura
  • Link

LINKS:
- Mostrá siempre el link completo de la nota.
- Usá formato HTML: <a href="URL" target="_blank">Ver nota</a>

FORMATO:
- Usá listas numeradas cuando haya varios ítems.
- No menciones documentos ni chunks.
"""

    user_prompt = f"""
CONTEXTO:
{context}

PREGUNTA:
{question}
"""

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    answer = completion.choices[0].message.content

    print("✅ RESPUESTA:", answer[:400])

    return jsonify({"answer": answer})

# ------------------------
# RUN
# ------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
