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
# PROMPT
# ------------------------

SYSTEM_PROMPT = """
Sos un asistente del Consejo de la Magistratura de la Ciudad Autónoma de Buenos Aires.
Respondés únicamente con la información incluida en el CONTEXTO provisto.
No uses conocimiento externo ni hagas suposiciones.

REGLAS OBLIGATORIAS:
- No inventes información que no esté explícitamente en el texto.
- Si un dato no aparece en el contexto, decí: "No se menciona en los textos".
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
            f"URL: {d.get('url','')}\n"
        )
    return "\n\n---\n\n".join(partes)

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

    # solo chunks con texto real
    chunks = [c for c in chunks if len(c.get("texto","")) > 200]

    # ------------------------
    # 3. DETECCIÓN DE MODO
    # ------------------------

    es_plenario = "plenario" in q_lower or "reunión" in q_lower or "sesión" in q_lower

    # ------------------------
    # 4. FILTRO POR MES
    # ------------------------

    mes_pedido = None
    for k, v in MESES.items():
        if k in q_lower:
            mes_pedido = v

    if mes_pedido:
        chunks = [c for c in chunks if c.get("mes") == mes_pedido]

    # ------------------------
    # 5. AGRUPAR POR DOCUMENTO
    # ------------------------

    docs = group_chunks_by_url(chunks)

    # ------------------------
    # 6. SELECCIÓN FINAL DE DOCS
    # ------------------------

    if es_plenario:
        # último o por mes → un solo documento
        docs_validos = [d for d in docs if d.get("fecha_iso")]

        if docs_validos:
            docs_validos.sort(
                key=lambda d: parse_date_iso(d.get("fecha_iso")) or datetime.min,
                reverse=True
            )
            docs_final = [docs_validos[0]]
        else:
            docs_final = docs[:1]
    else:
        # temática → varios documentos
        docs_final = docs[:8]

    print("📄 Documentos usados:", len(docs_final))
    for d in docs_final:
        print(" -", d.get("titulo"), d.get("url"))

    if not docs_final:
        return jsonify({"answer": "No encontré información relevante para la consulta."})

    # ------------------------
    # 7. CONTEXTO
    # ------------------------

    context = build_context(docs_final)

    user_prompt = f"""
CONTEXTO:
{context}

PREGUNTA:
{question}
"""

    # ------------------------
    # 8. OPENAI COMPLETION
    # ------------------------

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
