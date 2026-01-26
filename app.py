from flask import Flask, jsonify, request, render_template
import json
import os
import re
from datetime import datetime
import numpy as np
from openai import OpenAI

# ------------------------
# INIT
# ------------------------

client = OpenAI()
app = Flask(__name__)

DATA_FILE = "data.json"

# ------------------------
# LOAD DATA (opcional)
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
    meta = json.load(f)

with open("chunks.json", "r", encoding="utf-8") as f:
    chunks = json.load(f)

# normalizar embeddings
norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
embeddings_norm = embeddings / norms

print(f"✅ Embeddings cargados: {embeddings_norm.shape}")

# ------------------------
# FECHAS Y MESES
# ------------------------

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12
}

def detectar_mes(texto):
    t = texto.lower()
    for nombre, num in MESES.items():
        if nombre in t:
            return num
    return None

def pide_ultimo(texto):
    return bool(re.search(r"\bú|últim|reciente|más nuevo\b", texto.lower()))

# ------------------------
# SIMILITUD
# ------------------------

def cosine_sim(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

# ------------------------
# AGRUPAR POR URL (DOCUMENTO)
# ------------------------

def agrupar_por_url(indices, scores):
    docs = {}

    for idx, score in zip(indices, scores):
        m = meta[idx]
        c = chunks[idx]
        url = m.get("url")

        docs.setdefault(url, {
            "url": url,
            "titulo": m.get("titulo"),
            "fecha_iso": m.get("fecha_iso"),
            "anio": m.get("anio"),
            "mes": m.get("mes"),
            "textos": [],
            "score": 0
        })

        docs[url]["textos"].append(c.get("texto", ""))
        docs[url]["score"] = max(docs[url]["score"], score)

    for d in docs.values():
        d["texto"] = "\n".join(d["textos"])

    return list(docs.values())

# ------------------------
# FILTRO POR FECHA
# ------------------------

def filtrar_por_fecha(docs, pregunta):
    mes = detectar_mes(pregunta)
    quiere_ultimo = pide_ultimo(pregunta)

    filtrados = docs

    if mes:
        filtrados = [d for d in filtrados if d.get("mes") == mes]

    if quiere_ultimo and filtrados:
        filtrados = sorted(
            filtrados,
            key=lambda d: d.get("fecha_iso") or "",
            reverse=True
        )
        return filtrados[:1]

    return filtrados

# ------------------------
# CONTEXTO PARA PROMPT
# ------------------------

def build_context(docs):
    partes = []
    for d in docs:
        partes.append(
            f"TÍTULO: {d.get('titulo','')}\n"
            f"FECHA: {d.get('fecha_iso','')}\n"
            f"URL: {d.get('url','')}\n\n"
            f"{d.get('texto','')}\n"
        )
    return "\n\n---\n\n".join(partes)

# ------------------------
# PROMPT
# ------------------------

SYSTEM_PROMPT = """
Sos un asistente del Consejo de la Magistratura de la Ciudad Autónoma de Buenos Aires.
Respondés únicamente con la información incluida en el CONTEXTO provisto.
No uses conocimiento externo ni hagas suposiciones.

REGLAS OBLIGATORIAS:
- No inventes información que no esté explícitamente en el texto.
- Si un dato no aparece en el texto, decí claramente: "No se menciona en el texto".
- No mezcles información de documentos distintos.
- No infieras temas a partir de títulos: usá solo el contenido del texto.

CUANDO LA PREGUNTA SEA SOBRE UN PLENARIO O REUNIÓN:
- Enumerá los puntos tratados en forma de lista numerada.
- Incluí proyectos aprobados, reformas, protocolos, convenios, informes de comisiones
  y cualquier otra decisión mencionada.
- No limites la respuesta a un solo tema si el texto contiene varios.

CUANDO LA PREGUNTA SEA TEMÁTICA (por ejemplo: Frecuencia Judicial, IA, Lenguaje Claro):
- Explicá lo que el texto dice sobre ese tema, aunque no esté vinculado a un plenario.
- Podés resumir y unificar información de varios párrafos del mismo documento.

FORMATO:
- Usá listas numeradas si hay varios puntos.
- No menciones "documentos", "contexto" ni cómo funciona el sistema.
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

    # ------------------------
    # EMBEDDING DE PREGUNTA
    # ------------------------

    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    ).data[0].embedding

    q_vec = np.array(q_emb, dtype="float32")

    # ------------------------
    # RETRIEVAL
    # ------------------------

    sims = np.dot(embeddings_norm, q_vec) / np.linalg.norm(q_vec)

    TOP_K = 30
    top_idx = np.argsort(sims)[-TOP_K:][::-1]
    top_scores = sims[top_idx]

    docs = agrupar_por_url(top_idx, top_scores)

    docs = filtrar_por_fecha(docs, question)

    docs = sorted(docs, key=lambda d: d["score"], reverse=True)

    docs = docs[:3]

    if not docs:
        return jsonify({"answer": "No encontré información del período solicitado."})

    print("📄 Docs usados:")
    for d in docs:
        print(" -", d.get("titulo"), d.get("fecha_iso"))

    # ------------------------
    # CONTEXTO
    # ------------------------

    context = build_context(docs)

    # ------------------------
    # LLM
    # ------------------------

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"CONTEXTO:\n{context}\n\nPREGUNTA:\n{question}"
            }
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
