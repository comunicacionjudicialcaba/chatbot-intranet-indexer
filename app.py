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
# HELPERS
# ------------------------

MESES = {
    "enero":1, "febrero":2, "marzo":3, "abril":4, "mayo":5, "junio":6,
    "julio":7, "agosto":8, "septiembre":9, "octubre":10, "noviembre":11, "diciembre":12
}

def detectar_mes(texto):
    t = texto.lower()
    for k, v in MESES.items():
        if k in t:
            return v
    return None

def detectar_anio(texto):
    for y in range(2020, 2031):
        if str(y) in texto:
            return y
    return None

# ------------------------
# DETECCIÓN DE PLENARIO
# ------------------------
def tipo_plenario(item):
    titulo = (item.get("titulo","")).lower()
    texto = (item.get("texto","")).lower()

    # convocatoria (anuncio)
    if (
        "convocatoria" in titulo
        or "se convoca" in texto
        or "se realizará el plenario" in texto
        or "se celebrará el plenario" in texto
    ):
        return "convocatoria"

    # sesión real (crónica)
    indicadores_sesion = [
        "sesión plenaria",
        "plenario ordinario",
        "orden del día",
        "durante la sesión",
        "se aprobaron",
        "trataron los siguientes temas",
        "se celebró el plenario"
    ]

    if any(k in texto or k in titulo for k in indicadores_sesion):
        return "sesion"

    return "otro"
    
def tipo_plenario(item):
    titulo = (item.get("titulo","")).lower()
    texto = (item.get("texto","")).lower()

    # ---- CONVOCATORIA (anuncio previo) ----
    if (
        "convocatoria" in titulo
        or "se convoca" in texto
        or "se realizará el plenario" in texto
        or "se celebrará el plenario" in texto
    ):
        return "convocatoria"

    # ---- SESIÓN REAL (crónica del plenario) ----
    indicadores_sesion = [
        "sesión plenaria",
        "plenario ordinario",
        "orden del día",
        "durante la sesión",
        "se aprobaron",
        "se trató el temario",
        "se celebró el último plenario",
        "se celebró el plenario"
    ]

    if any(k in texto or k in titulo for k in indicadores_sesion):
        return "sesion"

    return "otro"

# ------------------------
# SEMANTIC SEARCH (TEMAS)
# ------------------------

def semantic_search(query_embedding, top_k=40):
    q = query_embedding / np.linalg.norm(query_embedding)
    sims = np.dot(embeddings_norm, q)
    top_idx = np.argsort(sims)[-top_k:][::-1]
    results = [metadata[i] for i in top_idx]
    scores = [float(sims[i]) for i in top_idx]
    return results, scores

# ------------------------
# AGRUPAR POR URL
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
# CONTEXTO
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
Respondés únicamente con la información incluida en los textos provistos.

REGLAS:
- No inventes datos.
- Si algo no aparece en los textos, decí: "No se menciona en los textos".
- No infieras por el título: usá principalmente el contenido del texto.

SI LA PREGUNTA ES TEMÁTICA:
- Podés usar varios textos.
- Listá las notas relevantes.
- Para cada una:
  • Título
  • Breve descripción
  • Link:
    <a href="URL" target="_blank">Ver nota</a>

SI LA PREGUNTA ES SOBRE UN EVENTO:
- Usá un solo texto.
- Enumerá todos los puntos tratados.

FORMATO:
- Usá listas cuando corresponda.
- Links siempre en HTML.
"""

# ------------------------
# ROUTES
# ------------------------

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    question = (data.get("question") or "").strip()
    q_lower = question.lower()

    print("🔎 Pregunta:", question)

    if not question:
        return jsonify({"answer": "No recibí la pregunta."})

    # =========================================================
    # 🟣 MODO PLENARIO (SIN LLM PARA LISTADOS)
    # =========================================================

    if "plenario" in q_lower:

        plenarios = [d for d in DATA if es_plenario(d)]

        mes_pedido = detectar_mes(q_lower)
        anio_pedido = detectar_anio(q_lower)

        if anio_pedido:
            plenarios = [p for p in plenarios if p.get("anio") == anio_pedido]

        if mes_pedido:
            plenarios = [p for p in plenarios if p.get("mes") == mes_pedido]

        plenarios.sort(key=lambda x: x.get("fecha_iso",""), reverse=True)

        # ---- LISTADO DE PLENARIOS ----
        if "cuáles" in q_lower or "cuales" in q_lower or "qué plenarios" in q_lower:

            if not plenarios:
                return jsonify({"answer": "No se registran plenarios para el período solicitado."})

            out = ["Estos fueron los plenarios registrados:\n"]
            for p in plenarios:
                out.append(
                    f"- {p.get('fecha','')} — {p.get('titulo','')} "
                    f'(<a href="{p.get("url")}" target="_blank">Ver nota</a>)'
                )
            return jsonify({"answer": "<br>".join(out)})

        # ---- CUÁNTOS ----
        if "cuántos" in q_lower or "cuantos" in q_lower:
            if anio_pedido:
                return jsonify({"answer": f"Durante {anio_pedido} se registran {len(plenarios)} plenarios."})
            return jsonify({"answer": f"Se registran {len(plenarios)} plenarios en los textos disponibles."})

        # ---- ÚLTIMO ----
        if "último" in q_lower or "ultimo" in q_lower:
            plenarios = plenarios[:1]

        if not plenarios:
            return jsonify({"answer": "No encontré plenarios para el período solicitado."})

        # ---- DETALLE DE UN PLENARIO ----
        doc = plenarios[0]

        prompt = f"""
TEXTO:
{doc.get("texto","")}

PREGUNTA:
{question}
"""

        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )

        answer = completion.choices[0].message.content
        return jsonify({"answer": answer})

    # =========================================================
    # 🟢 MODO TEMÁTICO (RAG)
    # =========================================================

    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    ).data[0].embedding

    chunks, scores = semantic_search(np.array(q_emb), top_k=60)

    KEYWORDS = ["frecuencia judicial", "mia", "lenguaje claro", "salud", "uma", "obra social", "paritaria", "fachada"]

    def keyword_score(c):
        t = (c.get("titulo","") + " " + c.get("texto","")).lower()
        return sum(2 for k in KEYWORDS if k in t and k in q_lower)

    chunks = sorted(chunks, key=lambda c: keyword_score(c), reverse=True)
    chunks = [c for c in chunks if len(c.get("texto","")) > 300]

    docs = group_chunks_by_url(chunks)[:6]

    if not docs:
        return jsonify({"answer": "No encontré información relacionada con tu consulta."})

    context = build_context(docs)

    prompt = f"""
TEXTOS:
{context}

PREGUNTA:
{question}
"""

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    answer = completion.choices[0].message.content
    return jsonify({"answer": answer})

# ------------------------
# RUN
# ------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
