from flask import Flask, jsonify, request, render_template
import json
import os
from datetime import datetime
import numpy as np
from openai import OpenAI
from collections import defaultdict

# ========================
# KEYWORD BOOST HELPERS
# ========================

STOPWORDS = {
    "el","la","los","las","de","del","y","o","en","un","una","por",
    "que","se","al","a","con","para","sobre","qué","cual","cuál",
    "fue","es","son","hubo","hay","ultimo","último","plenario"
}

INSTITUTIONAL_TERMS = {
    "uma", "paritaria", "paritarias", "obra", "social", "salario",
    "fachada", "edificio", "infraestructura", "aumento", "sueldo",
    "frecuencia", "podcast", "mia", "inteligencia", "artificial",
    "lenguaje", "claro"
}

def extract_keywords(text):
    words = [
        w.strip(".,¿?¡!()").lower()
        for w in text.split()
        if len(w) > 3 and w.lower() not in STOPWORDS
    ]
    return list(set(words))


def keyword_score(doc, keywords, full_query):
    score = 0
    texto = (doc.get("texto") or "").lower()
    titulo = (doc.get("titulo") or "").lower()

    if full_query.lower() in texto:
        score += 5
    if full_query.lower() in titulo:
        score += 8

    for kw in keywords:
        if kw in texto:
            score += 1
        if kw in titulo:
            score += 2
        if kw in INSTITUTIONAL_TERMS and kw in texto:
            score += 4

    return score


# ------------------------
# INIT
# ------------------------

client = OpenAI()
app = Flask(__name__)

DATA_FILE = "data.json"

# ------------------------
# LOAD DATA (buscador)
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

def build_context(docs, max_docs=6):
    partes = []
    for d in docs[:max_docs]:
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

REGLAS OBLIGATORIAS:
- No inventes información que no esté explícitamente en el texto.
- Si un dato no aparece en el texto, decí: "No se menciona en los textos".
- No mezcles información de documentos distintos cuando describas decisiones formales.
- No infieras temas solo por el título: usá principalmente el contenido del texto.

TIPOS DE RESPUESTA:

SI LA PREGUNTA ES SOBRE UN PLENARIO O REUNIÓN:
- Respondé usando UN solo documento (el más reciente o el del mes pedido).
- Enumerá todos los puntos tratados:
  proyectos, reformas, protocolos, convenios, informes de comisiones y decisiones.
- Usá lista numerada.

SI LA PREGUNTA ES TEMÁTICA (ej: Frecuencia Judicial, IA, Lenguaje Claro, MIA, etc):
- Podés usar VARIOS documentos del contexto.
- Listá las notas relevantes.
- Para cada nota indicá:
  • Título
  • Breve descripción (1–2 líneas)
  • Link clickeable a la nota (usar HTML <a href>)

FORMATO:
- Usá listas cuando corresponda.
- Los links deben ir como HTML:
  <a href="URL" target="_blank">Ver nota</a>
- No menciones "documentos", "chunks" ni "contexto".
- No expliques cómo funciona el sistema ni el modelo.
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
    # 1. EMBEDDING
    # ------------------------

    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    ).data[0].embedding

    # ------------------------
    # 2. RETRIEVAL
    # ------------------------

    chunks, scores = semantic_search(np.array(q_emb), top_k=60)

    # chunks con texto útil
    chunks = [c for c in chunks if len(c.get("texto","")) > 200]

    # evitar convocatorias cuando se habla de plenario
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

    if "último" in q_lower or "ultimo" in q_lower or "reciente" in q_lower:
        fechas = [parse_date_iso(c.get("fecha_iso")) for c in chunks if c.get("fecha_iso")]
        if fechas:
            max_fecha = max(fechas)
            chunks = [
                c for c in chunks
                if parse_date_iso(c.get("fecha_iso")) == max_fecha
            ]

    if not chunks:
        return jsonify({"answer": "No encontré información del período solicitado."})

    # ------------------------
    # 4. AGRUPAR POR DOCUMENTO
    # ------------------------

    docs = group_chunks_by_url(chunks)

    # ------------------------
    # 5. KEYWORD BOOST
    # ------------------------

    keywords = extract_keywords(question)
    scored_docs = []

    for d in docs:
        s = keyword_score(d, keywords, question)
        scored_docs.append((s, d))

    scored_docs.sort(key=lambda x: x[0], reverse=True)
    docs = [d for s, d in scored_docs]

    # ------------------------
    # 6. CONTEXTO
    # ------------------------

    # modo plenario → un solo documento
    if "plenario" in q_lower:
        context_docs = docs[:1]
    else:
        context_docs = docs[:6]

    context = build_context(context_docs)

    # ------------------------
    # 7. LLM
    # ------------------------

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"CONTEXTO:\n{context}\n\nPREGUNTA:\n{question}"}
    ]

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
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
