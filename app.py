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
# LOAD DATA
# ------------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

DATA = load_data()

# ------------------------
# LOAD EMBEDDINGS
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

def semantic_search(query_embedding, top_k=60):
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

def keyword_recall(query, records, limit=30):
    q = query.lower()
    hits = []
    for r in records:
        t = (r.get("titulo","") + " " + r.get("texto","")).lower()
        if q in t:
            hits.append(r)
    return hits[:limit]

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
            f"Texto:\n{d.get('texto','')}\n"
            f"URL: {d.get('url','')}\n"
        )
    return "\n---\n".join(partes)

# ------------------------
# PROMPT
# ------------------------

SYSTEM_PROMPT = """
Sos un asistente del Consejo de la Magistratura de la Ciudad Autónoma de Buenos Aires.
Respondés únicamente con la información incluida en el CONTEXTO provisto.
No uses conocimiento externo ni hagas suposiciones.

REGLAS:
- No inventes datos.
- Si algo no figura, decí: "No se menciona en el texto".
- No infieras por títulos: usá solo el contenido del texto.

PLENARIOS / EVENTOS:
- Enumerá todos los temas tratados.
- Incluí proyectos, protocolos, reformas, convenios, informes y resoluciones.
- Usá solo el documento del evento.

PREGUNTAS TEMÁTICAS:
- Podés usar varios textos del contexto.
- Integrá la información disponible sobre el tema.
- Podés resumir y agrupar por puntos.

FORMATO:
- Usá listas cuando haya varios ítems.
- No menciones documentos ni contexto.
"""

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
    # DETECTAR PREGUNTA TEMÁTICA
    # ------------------------

    TEMAS = [
        "frecuencia judicial",
        "podcast",
        "mia",
        "inteligencia artificial",
        "lenguaje claro",
        "desafío claro",
        "cfj",
        "capacitación",
        "convenio",
        "universidad",
    ]

    es_tematica = any(t in q_lower for t in TEMAS)
    es_plenario = "plenario" in q_lower or "sesión" in q_lower or "reunión" in q_lower

    # ------------------------
    # 1. EMBEDDING
    # ------------------------

    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    ).data[0].embedding

    # ------------------------
    # 2. RETRIEVAL SEMÁNTICO
    # ------------------------

    chunks_sem, _ = semantic_search(np.array(q_emb), top_k=60)
    chunks_sem = [c for c in chunks_sem if len(c.get("texto","")) > 200]

    # ------------------------
    # 3. KEYWORD RECALL (solo temático)
    # ------------------------

    chunks_kw = []
    if es_tematica:
        chunks_kw = keyword_recall(question, metadata, limit=40)
        chunks_kw = [c for c in chunks_kw if len(c.get("texto","")) > 200]

    # merge sin duplicados
    by_url = {}
    for c in chunks_sem + chunks_kw:
        by_url[c["url"]] = c
    chunks = list(by_url.values())

    # ------------------------
    # FILTRO CRÓNICAS PLENARIO
    # ------------------------

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
    # FILTROS FECHA
    # ------------------------

    MESES = {
        "enero":1, "febrero":2, "marzo":3, "abril":4, "mayo":5, "junio":6,
        "julio":7, "agosto":8, "septiembre":9, "octubre":10, "noviembre":11, "diciembre":12
    }

    mes_pedido = None
    for k, v in MESES.items():
        if k in q_lower:
            mes_pedido = v

    if mes_pedido:
        chunks = [c for c in chunks if c.get("mes") == mes_pedido]

    if "último" in q_lower or "ultimo" in q_lower or "reciente" in q_lower:
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
        return jsonify({"answer": "No encontré información del período o tema solicitado."})

    # ------------------------
    # 4. AGRUPAR POR DOC
    # ------------------------

    docs = group_chunks_by_url(chunks)

    if es_tematica:
        selected_docs = docs[:6]
    elif es_plenario:
        selected_docs = docs[:1]
    else:
        selected_docs = docs[:2]

    # ------------------------
    # 5. CONTEXTO
    # ------------------------

    context = build_context(selected_docs)

    # ------------------------
    # 6. LLM
    # ------------------------

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"CONTEXTO:\n{context}\n\nPREGUNTA:\n{question}"
        }
    ]

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
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
