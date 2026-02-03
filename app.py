from flask import Flask, jsonify, request, render_template
import json
import os
import requests
import numpy as np
from openai import OpenAI
from collections import defaultdict
import unicodedata
from bs4 import BeautifulSoup

GOOGLE_FORM_URL = os.environ.get("GOOGLE_FORM_URL")

# =========================================================
# INIT
# =========================================================

client = OpenAI()
app = Flask(__name__)

DATA_FILE = "data.json"

# =========================================================
# LOAD DATA
# =========================================================

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

DATA = load_data()

# =========================================================
# LOAD EMBEDDINGS (RAG)
# =========================================================

print("🔄 Cargando embeddings...")

embeddings = np.load("embeddings.npy")

with open("meta.json", "r", encoding="utf-8") as f:
    metadata = json.load(f)

norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
embeddings_norm = embeddings / norms

print(f"✅ Embeddings cargados: {embeddings_norm.shape}")

# =========================================================
# NORMALIZACIÓN TEXTO
# =========================================================

def normalizar_texto(t):
    if not t:
        return ""
    t = t.lower()
    t = ''.join(
        c for c in unicodedata.normalize('NFD', t)
        if unicodedata.category(c) != 'Mn'
    )
    return t

# =========================================================
# HELPERS FECHA
# =========================================================

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

# =========================================================
# TIPO DE PLENARIO
# =========================================================

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

    indicadores = [
        "sesion plenaria",
        "plenario ordinario",
        "orden del dia",
        "durante la sesion",
        "se aprobaron",
        "se trato el temario",
        "se celebro el ultimo plenario",
        "se celebro el plenario"
    ]

    if any(k in texto or k in titulo for k in indicadores):
        return "sesion"

    return "otro"

# =========================================================
# DETECCIÓN DE CONSULTA
# =========================================================

CARGO_KEYWORDS = [
    "secretaria", "direccion", "oficina", "programa",
    "departamento", "coordinacion", "unidad", "gerencia", "area"
]

NORMATIVA_KEYWORDS = ["resolucion", "res. cm", "normativa"]
ISO_KEYWORDS = ["iso", "normasiso9001", "gestion de calidad", "sgc"]
SERVICIO_KEYWORDS = ["servicio", "corte", "mantenimiento", "fumigacion"]
CFJ_KEYWORDS = [
    "curso", "cursos", "capacitacion", "capacitación", "capacitaciones",
    "cfj", "formacion judicial", "formación judicial",
    "taller", "seminario", "beca", "becas", "centro de formacion judicial", "centro de formación judicial"
]

def es_busqueda_area(q_norm):
    return any(k in q_norm for k in CARGO_KEYWORDS)

def es_busqueda_normativa(q_norm):
    return any(k in q_norm for k in NORMATIVA_KEYWORDS)

def es_busqueda_iso(q_norm):
    return any(k in q_norm for k in ISO_KEYWORDS)

def es_busqueda_servicio(q_norm):
    return any(k in q_norm for k in SERVICIO_KEYWORDS)

def es_busqueda_cfj(q_norm):
    return any(k in q_norm for k in CFJ_KEYWORDS)

def es_busqueda_persona(q_original):
    palabras = q_original.strip().split()
    if len(palabras) > 7:
        return False
    return sum(1 for p in palabras if p[:1].isupper()) >= 1

# =========================================================
# PROMPTS
# =========================================================

SYSTEM_PROMPT = """
Sos un asistente institucional del Consejo de la Magistratura de la Ciudad Autónoma de Buenos Aires.

Respondés exclusivamente con la información contenida en las notas provistas.

- No inventes datos.
- Organizá la información con claridad.

🔧 BLINDAJE:
- Algunas notas pueden no tener aún desarrollo de texto.
- Si una nota refiere directamente al tema consultado por su TÍTULO,
  utilizá esa información y aclaralo explícitamente.
- No descartes una nota relevante solo porque su texto esté vacío.
- No respondas “no se menciona” si existe una nota cuyo título coincide
  claramente con la consulta.
"""

PROMPT_ISO = """
La consulta refiere al Sistema de Gestión de Calidad o ISO 9001.
Clasificá información confirmada. No inventes certificaciones.
"""

PROMPT_PLENARIO = """
La consulta refiere a plenarios del Consejo.
Indicá fecha, tipo y decisiones principales.
"""

PROMPT_SERVICIO = """
La consulta refiere a servicios operativos.
Indicá servicio, fechas y área responsable.
"""

PROMPT_NORMATIVA = """
La consulta refiere a normativa.
No reemplaces el buscador normativo oficial.
"""

PROMPT_CFJ = """
La consulta refiere EXCLUSIVAMENTE a la oferta vigente del
Centro de Formación Judicial (CFJ).

INSTRUCCIONES OBLIGATORIAS:
- Respondé SOLO con la información listada en el contexto provisto.
- NO menciones notas, documentos internos ni embeddings.
- NO digas “no se dispone de información”.
- NO inventes URLs ni secciones.
- Si hay cursos o becas listados, ENUMERALOS.
- Si no hubiera resultados, indicá: “La oferta visible en el sitio oficial puede variar”.

El sitio oficial del CFJ utiliza:
- https://cfj.gov.ar/capacitacion.php
- https://cfj.gov.ar/becas.php
"""

# =========================================================
# CFJ – FUENTE VIVA
# =========================================================

CFJ_CAP_URL = "https://cfj.gov.ar/capacitacion.php"
CFJ_BECAS_URL = "https://cfj.gov.ar/becas.php"

def obtener_items_cfj(url):
    r = requests.get(url, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    items = []

    # Buscar títulos comunes de actividades
    for tag in soup.find_all(["h2", "h3", "strong", "p"]):
        texto = tag.get_text(strip=True)

        if not texto:
            continue

        # Filtro básico de relevancia
        if len(texto) < 20:
            continue

        if not any(k in texto.lower() for k in [
            "curso", "seminario", "taller", "capacitación", "formación", "jornada"
        ]):
            continue

        items.append({
            "titulo": texto,
            "url": url
        })

    # deduplicar
    vistos = set()
    out = []
    for i in items:
        if i["titulo"] not in vistos:
            vistos.add(i["titulo"])
            out.append(i)

    return out[:10]


def responder_cfj(question):
    cursos = obtener_items_cfj(CFJ_CAP_URL)
    becas = obtener_items_cfj(CFJ_BECAS_URL)

    contexto = []
    for c in cursos:
        contexto.append(f"- {c['titulo']} ({c['url']})")
    for b in becas:
        contexto.append(f"- {b['titulo']} ({b['url']})")

    prompt = f"""
INFORMACIÓN OFICIAL CFJ:
{chr(10).join(contexto)}

PREGUNTA:
{question}
"""

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": PROMPT_CFJ},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    answer = completion.choices[0].message.content
    answer += (
        "<br><br><b>🔗 Oferta completa:</b><br>"
        f'<a href="{CFJ_CAP_URL}" target="_blank">Centro de Formación Judicial</a>'
    )
    return jsonify({"answer": answer})

# =========================================================
# RAG
# =========================================================

def semantic_search(query_embedding, top_k=40):
    q = query_embedding / np.linalg.norm(query_embedding)
    sims = np.dot(embeddings_norm, q)
    idx = np.argsort(sims)[-top_k:][::-1]
    return [metadata[i] for i in idx]

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

def build_context(docs):
    partes = []
    for d in docs:
        texto = (d.get("texto") or "").strip()

        # 🔧 CAMBIO 2 – nota sin texto
        if not texto:
            texto = "⚠️ Nota sin desarrollo de contenido al momento."

        partes.append(
            f"Título: {d.get('titulo','')}\n"
            f"Fecha: {d.get('fecha','')}\n"
            f"Texto:\n{texto}\n"
        )
    return "\n---\n".join(partes)


# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    question = (data.get("question") or "").strip()
    q_norm = normalizar_texto(question)
        # 🔧 CAMBIO FINAL – Fallback léxico por título (notas sin texto / nuevas)
    coincidencias_titulo = []
    for d in DATA:
        titulo_norm = normalizar_texto(d.get("titulo",""))
        if titulo_norm and any(p in titulo_norm for p in q_norm.split()):
            coincidencias_titulo.append(d)

    if coincidencias_titulo:
        # armamos respuesta directa sin RAG
        partes = []
        for d in coincidencias_titulo[:5]:
            partes.append(
                f"• {d.get('titulo','')} — "
                f'<a href="{d.get("url")}" target="_blank">Ver nota</a>'
            )

        answer = (
            "Se registran las siguientes notas vinculadas al tema consultado. "
            "Algunas publicaciones pueden no contar aún con el desarrollo completo del contenido.<br><br>"
            + "<br>".join(partes)
        )

        return jsonify({"answer": answer})


    if not question:
        return jsonify({"answer": "No recibí la pregunta."})
        
            # 🔴 PRIORIDAD CFJ
    if (
        "cfj" in q_norm
        or "centro de formacion judicial" in q_norm
        or "centro de formación judicial" in q_norm
    ):
        return responder_cfj(question)  

    # ---- PROMPT EXTRA ----
    prompt_extra = ""
    if es_busqueda_iso(q_norm):
        prompt_extra = PROMPT_ISO
    elif "plenario" in q_norm:
        prompt_extra = PROMPT_PLENARIO
    elif es_busqueda_servicio(q_norm):
        prompt_extra = PROMPT_SERVICIO
    elif es_busqueda_normativa(q_norm):
        prompt_extra = PROMPT_NORMATIVA

    # ---- RAG GENERAL ----
    q_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=q_norm
    ).data[0].embedding

    chunks = semantic_search(np.array(q_emb), top_k=80)
        # 🔧 CAMBIO 3 – Re-rank por título cuando no hay texto
    palabras_query = q_norm.split()

    for c in chunks:
        c["_boost"] = 0
        if not c.get("texto"):
            titulo_norm = normalizar_texto(c.get("titulo",""))
            if any(p in titulo_norm for p in palabras_query):
                c["_boost"] = 1

    # Prioriza notas con título relevante y sin texto
    chunks.sort(key=lambda x: x.get("_boost", 0), reverse=True)

    docs = group_chunks_by_url(chunks)[:8]

    if not docs:
        return jsonify({"answer": "No encontré información relacionada."})

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
            {"role": "system", "content": prompt_extra},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    answer = completion.choices[0].message.content

    links = []
    for d in docs:
        if d.get("url"):
            links.append(
                f'• {d.get("titulo","")} — '
                f'<a href="{d.get("url")}" target="_blank">Ver nota</a>'
            )

    if links:
        answer += "<br><br><b>🔗 Notas relacionadas:</b><br>" + "<br>".join(links)

    return jsonify({"answer": answer})

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
