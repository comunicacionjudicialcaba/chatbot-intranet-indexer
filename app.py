from flask import Flask, jsonify, request, render_template
import json
import os
import requests
import numpy as np
from openai import OpenAI
from collections import defaultdict
import unicodedata

GOOGLE_FORM_URL = os.environ.get("GOOGLE_FORM_URL")

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
# NORMALIZACIÓN TEXTO
# ------------------------

def normalizar_texto(t):
    if not t:
        return ""
    t = t.lower()
    t = ''.join(
        c for c in unicodedata.normalize('NFD', t)
        if unicodedata.category(c) != 'Mn'
    )
    return t

# ------------------------
# HELPERS FECHA
# ------------------------

MESES = {
    "enero":1, "febrero":2, "marzo":3, "abril":4, "mayo":5, "junio":6,
    "julio":7, "agosto":8, "septiembre":9, "octubre":10, "noviembre":11, "diciembre":12
}

def detectar_mes(texto_norm):
    for k, v in MESES.items():
        if k in texto_norm:
            return v
    return None

def detectar_anio(texto_norm):
    for y in range(2020, 2031):
        if str(y) in texto_norm:
            return y
    return None

# ------------------------
# TIPO DE PLENARIO
# ------------------------

def tipo_plenario(item):
    titulo = normalizar_texto(item.get("titulo",""))
    texto = normalizar_texto(item.get("texto",""))

    if (
        "convocatoria" in titulo
        or "se convoca" in texto
        or "se realizara el plenario" in texto
        or "se celebrara el plenario" in texto
    ):
        return "convocatoria"

    indicadores_sesion = [
        "sesion plenaria",
        "plenario ordinario",
        "orden del dia",
        "durante la sesion",
        "se aprobaron",
        "se trato el temario",
        "se celebro el ultimo plenario",
        "se celebro el plenario"
    ]

    if any(k in texto or k in titulo for k in indicadores_sesion):
        return "sesion"

    return "otro"

# ------------------------
# DETECCIÓN PERSONA / ÁREA / NORMATIVA
# ------------------------

CARGO_KEYWORDS = [
    "secretaria", "direccion", "oficina", "programa",
    "departamento", "coordinacion", "unidad", "gerencia", "area"
]

NORMATIVA_KEYWORDS = ["resolucion", "res. cm", "normativa"]

def es_busqueda_area(q_norm):
    return any(k in q_norm for k in CARGO_KEYWORDS)

def es_busqueda_normativa(q_norm):
    return any(k in q_norm for k in NORMATIVA_KEYWORDS)

def es_busqueda_persona(q_original):
    palabras = q_original.strip().split()
    if len(palabras) > 7:
        return False
    return sum(1 for p in palabras if p[:1].isupper()) >= 1

# ------------------------
# SEMANTIC SEARCH (RAG)
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
# CONTEXTO PROMPT
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
# PROMPT SISTEMA
# ------------------------

SYSTEM_PROMPT = """
Sos un asistente institucional del Consejo de la Magistratura de la Ciudad Autónoma de Buenos Aires.

Respondés exclusivamente con la información contenida en las notas provistas.

CRITERIOS GENERALES:
- No inventes datos ni hechos.
- No transcribas normas completas.
- No respondas “no se menciona” si el texto permite una clasificación razonable.
- Organizá la información de forma clara y útil para el personal judicial.

USO DEL CONTENIDO:
- Podés interpretar el lenguaje institucional (por ejemplo: procesos en auditoría, implementación, experiencia piloto).
- Los hashtags institucionales (ej. #normasiso9001, #plenario) son señales válidas de clasificación temática.
- Podés agrupar información por tipo, estado o área cuando el texto lo permita.

FORMATO:
- Usá listas y subtítulos.
- No repitas texto innecesario.
- Los links se agregan fuera del texto explicativo.
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

# =========================================================
# 💬 CHAT
# =========================================================

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()

    question = (data.get("question") or "").strip()
    q_norm = normalizar_texto(question)

    print("🔎 Pregunta:", question)

    if not question:
        return jsonify({"answer": "No recibí la pregunta."})

    # =========================================================
    # 🟣 MODO PLENARIO
    # =========================================================

    if "plenario" in q_norm:

        plenarios = [d for d in DATA if tipo_plenario(d) != "otro"]

        mes_pedido = detectar_mes(q_norm)
        anio_pedido = detectar_anio(q_norm)

        if anio_pedido:
            plenarios = [p for p in plenarios if p.get("anio") == anio_pedido]

        if mes_pedido:
            plenarios = [p for p in plenarios if p.get("mes") == mes_pedido]

        plenarios.sort(key=lambda x: x.get("fecha_iso",""), reverse=True)

        # ---- LISTADO ----
        if "cuales" in q_norm:
            if not plenarios:
                return jsonify({"answer": "No se registran plenarios para el período solicitado."})

            out = ["Estos fueron los plenarios registrados:<br>"]
            for p in plenarios:
                out.append(
                    f"- {p.get('fecha','')} — {p.get('titulo','')} "
                    f'(<a href="{p.get("url")}" target="_blank">Ver nota</a>)'
                )
            return jsonify({"answer": "<br>".join(out)})

        # ---- CUÁNTOS ----
        if "cuantos" in q_norm:
            if anio_pedido:
                return jsonify({"answer": f"Durante {anio_pedido} se registran {len(plenarios)} plenarios."})
            return jsonify({"answer": f"Se registran {len(plenarios)} plenarios en los textos disponibles."})

        # ---- ÚLTIMO ----
        if "ultimo" in q_norm:
            plenarios = plenarios[:1]

        if not plenarios:
            return jsonify({"answer": "No encontré plenarios para el período solicitado."})

        # ---- DETALLE ----
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

        # ✅ AGREGAR LINK GARANTIZADO DESDE BACKEND
        url = doc.get("url")
        if url:
            answer += (
                "<br><br><b>🔗 Nota completa:</b><br>"
                f'<a href="{url}" target="_blank">Ver nota del plenario</a>'
            )

        return jsonify({"answer": answer})

    # =========================================================
    # 🔵 PERSONA / ÁREA / TEMÁTICO / NORMATIVA (RAG)
    # =========================================================

    modo_persona = es_busqueda_persona(question)
    modo_area = es_busqueda_area(q_norm)
    modo_normativa = es_busqueda_normativa(q_norm)

    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=q_norm
    ).data[0].embedding

    chunks, scores = semantic_search(np.array(q_emb), top_k=100)

    if not (modo_persona or modo_area):
        chunks = [c for c in chunks if len(c.get("texto","")) > 250]

    docs = group_chunks_by_url(chunks)[:10]

    if not docs:
        return jsonify({"answer": "No encontré información relacionada con tu consulta."})

    context = build_context(docs)

    if modo_persona or modo_area:
        prompt = f"""
TEXTOS:
{context}

PREGUNTA:
Listá todas las notas relevantes relacionadas con la consulta.
Para cada una indicá:
- Título
- Fecha
- En qué contexto aparece la persona o el área
- Link

Consulta: {question}
"""
    else:
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

    # 👉 Leyenda para normativa
    if modo_normativa:
        answer += (
            "<br><br><b>ℹ️ Para búsquedas normativas usá el buscador oficial:</b><br>"
            '<a href="https://buscador.jusbaires.gob.ar" target="_blank">'
            "👉 buscador.jusbaires.gob.ar</a>"
        )

    return jsonify({"answer": answer})

# =========================================================
# ✉ FEEDBACK
# =========================================================

@app.route("/feedback", methods=["POST"])
def feedback():
    data = request.get_json()

    payload = {
        "entry.2141687049": data.get("question", ""),
        "entry.461024130": data.get("answer", ""),
        "entry.446421198": data.get("rating", ""),
        "entry.2031885759": data.get("comment", ""),
    }

    try:
        r = requests.post(GOOGLE_FORM_URL, data=payload, timeout=10)
        print("✅ Feedback enviado a Google Forms:", r.status_code)
    except Exception as e:
        print("❌ Error enviando feedback:", e)

    return jsonify({"status": "ok"})

# ------------------------
# RUN
# ------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
