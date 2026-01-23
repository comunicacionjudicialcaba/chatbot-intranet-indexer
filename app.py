from flask import Flask, jsonify, request, render_template
import json, os
from datetime import datetime
import numpy as np
from openai import OpenAI

client = OpenAI()

app = Flask(__name__)


DATA_FILE = "data.json"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# ------------------------
# LOAD DATA
# ------------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

DATA = load_data()

# ------------------------
# LOAD EMBEDDINGS
# ------------------------
print("🔄 Cargando embeddings...")

embeddings = np.load("embeddings.npy")  # shape: (N, dim)

with open("meta.json", encoding="utf-8") as f:
    metadata = json.load(f)

# Normalizamos para similitud coseno
norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
embeddings_norm = embeddings / norms

print(f"✅ Embeddings cargados: {embeddings_norm.shape}")

# ------------------------
# SEMANTIC SEARCH
# ------------------------

def semantic_search(query_embedding, top_k=6):
    # normalizar query
    q = query_embedding / np.linalg.norm(query_embedding)

    # coseno = producto punto (porque ya está normalizado)
    sims = np.dot(embeddings_norm, q)

    # top K
    top_idx = np.argsort(sims)[-top_k:][::-1]

    results = [metadata[i] for i in top_idx]
    scores = [float(sims[i]) for i in top_idx]

    return results, scores

# ------------------------
# HELPERS
# ------------------------

def parse_date(fecha):
    try:
        return datetime.strptime(fecha.strip(),"%d/%m/%Y")
    except:
        return datetime.min

def safe(v):
    return v if v not in [None, "", "null"] else ""

# ------------------------
# BUILD CONTEXT
# ------------------------
def build_context(chunks):
    partes = []

    for c in chunks:
        partes.append(
            f"Título: {c.get('titulo','')}\n"
            f"Fecha: {c.get('fecha','')}\n"
            f"Tipo: {c.get('tipo','')}\n"
            f"Texto:\n{c.get('text','')}\n"
            f"URL: {c.get('url','')}\n"
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
# SEARCH
# ------------------------

@app.route("/search")
def search():
    q = request.args.get("q","").lower().strip()
    year = request.args.get("year","").strip()

    res = []

    for n in DATA:
        titulo = safe(n.get("titulo","")).lower()
        texto = safe(n.get("texto","")).lower()
        fecha = safe(n.get("fecha",""))

        fulltext = f"{titulo} {texto}"

        if q and q not in fulltext:
            continue

        if year and not fecha.endswith(year):
            continue

        res.append(n)

    res.sort(key=lambda x: parse_date(x.get("fecha","")), reverse=True)

    return jsonify(res[:50])

# ------------------------
# CHAT
# ------------------------

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    question = data.get("message", "").strip()

    if not question:
        return jsonify({"reply": "No recibí la pregunta."})

    # 1. embedding de la pregunta
    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    ).data[0].embedding

    # 2. búsqueda semántica
    chunks, scores = semantic_search(np.array(q_emb), top_k=6)

    # 3. contexto
    context = build_context(chunks)

    # 4. prompt
    system = (
        "Sos un asistente interno del Poder Judicial de la CABA. "
        "Respondé solo usando la información del contexto. "
        "Si no hay datos suficientes, indicá que no hay información disponible. "
        "Mencioná fechas y referencias cuando sea posible."
    )

    user_prompt = f"""
Contexto:
{context}

Pregunta:
{question}
"""

    # 5. llamada al modelo
    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    answer = completion.choices[0].message.content

    return jsonify({"answer": answer})

print("🔎 Pregunta:", question)
print("📦 Chunks recuperados:", len(chunks))
for c, s in zip(chunks, scores):
    print(f" - {c.get('titulo')} ({s:.3f})")
    
# ------------------------
# RUN
# ------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT",8080))
    app.run(host="0.0.0.0", port=port)
