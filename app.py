from flask import Flask, jsonify, request, render_template
import json
import os
from datetime import datetime
import numpy as np
from openai import OpenAI
from collections import defaultdict

# ======================
# INIT
# ======================

client = OpenAI()
app = Flask(__name__)

DATA_FILE = "data.json"

# ======================
# LOAD DATA
# ======================

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

DATA = load_data()

# ======================
# LOAD EMBEDDINGS (TEMÁTICO)
# ======================

print("🔄 Cargando embeddings...")

embeddings = np.load("embeddings.npy")
with open("meta.json", "r", encoding="utf-8") as f:
    metadata = json.load(f)

norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
embeddings_norm = embeddings / norms

print(f"✅ Embeddings cargados: {embeddings_norm.shape}")

# ======================
# HELPERS FECHA
# ======================

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

def parse_date_iso(fecha_iso):
    try:
        return datetime.strptime(fecha_iso, "%Y-%m-%d")
    except:
        return None

# ======================
# SEMANTIC SEARCH (TEMAS)
# ======================

def semantic_search(query_embedding, top_k=40):
    q = query_embedding / np.linalg.norm(query_embedding)
    sims = np.dot(embeddings_norm, q)
    top_idx = np.argsort(sims)[-top_k:][::-1]
    results = [metadata[i] for i in top_idx]
    scores = [float(sims[i]) for i in top_idx]
    return results, scores

# ======================
# KEYWORD BOOST (SOLO TEMAS)
# ======================

KEYWORDS = [
    "frecuencia judicial", "mia", "lenguaje claro", "inteligencia artificial",
    "uma", "obra social", "salud", "paritaria", "acuerdo salarial",
    "fachada", "edificio", "infraestructura"
]

def keyword_score(doc, q_lower):
    score = 0
    texto = (doc.get("titulo","") + " " + doc.get("texto","")).lower()
    for kw in KEYWORDS:
        if kw in q_lower and kw in texto:
            score += 2
    return score

# ======================
# GROUP BY URL
# ======================

def group_chunks_by_url(chunks):
    docs = defaultdict(list)
    for c in chunks:
        docs[c["url"]].append(c)

    grouped = []
    for url, parts in docs.items():
        base = parts[0].copy()
        base["texto"] = "\n".join(p.get("texto","") for p in parts)
        grouped.append(base)

    return grouped

# ======================
# BUILD CONTEXT
# ======================

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

# ======================
# SYSTEM PROMPT
# ======================

SYSTEM_PROMPT = """
Sos un asistente del Consejo de la Magistratura de la Ciudad Autónoma de Buenos Aires.
Respondés únicamente con la información incluida en el CONTEXTO provisto.
No uses conocimiento externo ni hagas suposiciones.

REGLAS OBLIGATORIAS:
- No inventes información.
- Si un dato no aparece, decí: "No se menciona en los textos".
- No infieras solo por títulos: usá principalmente el texto.

SI LA PREGUNTA ES SOBRE UN PLENARIO:
- Respondé usando UN solo documento.
- Enumerá todos los puntos tratados.
- Usá lista numerada.

SI LA PREGUNTA ES TEMÁTICA:
- Podés usar VARIOS documentos.
- Listá las notas relevantes.
- Para cada nota indicá:
  • Título
  • Breve descripción
  • Link clickeable:
    <a href="URL" target="_blank">Ver nota</a>

FORMATO:
- Usá listas cuando corresponda.
- No menciones documentos, chunks ni contexto.
"""

# ======================
# ROUTES
# ======================

@app.route("/")
def home():
    return render_template("index.html")

# ======================
# CHAT
# ======================

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    question = (data.get("question") or "").strip()
    q_lower = question.lower()

    if not question:
        return jsonify({"answer": "No recibí la pregunta."})

    # ======================
    # DETECTAR MODO PLENARIO
    # ======================

    es_plenario = "plenario" in q_lower or "sesión" in q_lower

    mes_pedido = None
    for k, v in MESES.items():
        if k in q_lower:
            mes_pedido = v

    anio_pedido = None
    for y in ["2023", "2024", "2025", "2026"]:
        if y in q_lower:
            anio_pedido = int(y)

    # ======================
    # 🏛 MODO PLENARIO (DATA)
    # ======================

    if es_plenario:
        plenarios = [
            d for d in DATA
            if "plenario" in (d.get("titulo","")+d.get("texto","")).lower()
        ]

        if anio_pedido:
            plenarios = [d for d in plenarios if d.get("anio") == anio_pedido]

        if mes_pedido:
            plenarios = [d for d in plenarios if d.get("mes") == mes_pedido]

        if "cuántos" in q_lower or "cuantos" in q_lower:
            return jsonify({
                "answer": f"En el período solicitado se registran {len(plenarios)} plenarios."
            })

        if "último" in q_lower or "reciente" in q_lower:
            plenarios = sorted(plenarios, key=lambda x: x.get("fecha_iso",""))
            plenarios = plenarios[-1:] if plenarios else []

        if not plenarios:
            return jsonify({"answer": "No encontré información del período solicitado."})

        doc = plenarios[0]
        context = build_context([doc])

    # ======================
    # 🔍 MODO TEMÁTICO (RAG)
    # ======================

    else:
        q_emb = client.embeddings.create(
            model="text-embedding-3-small",
            input=question
        ).data[0].embedding

        chunks, scores = semantic_search(np.array(q_emb), top_k=40)
        chunks = [c for c in chunks if len(c.get("texto","")) > 200]

        # keyword boost
        scored = []
        for c, s in zip(chunks, scores):
            s += keyword_score(c, q_lower)
            scored.append((c, s))

        scored.sort(key=lambda x: x[1], reverse=True)
        chunks = [c for c, _ in scored[:25]]

        docs = group_chunks_by_url(chunks)
        context = build_context(docs[:5])

    # ======================
    # LLM
    # ======================

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"CONTEXTO:\n{context}\n\nPREGUNTA:\n{question}"}
        ],
        temperature=0.2,
    )

    answer = completion.choices[0].message.content
    return jsonify({"answer": answer})

# ======================
# RUN
# ======================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
