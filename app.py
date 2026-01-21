from flask import Flask, jsonify, request, render_template
import json
import os
import requests
from datetime import datetime

app = Flask(__name__)

DATA_FILE = "data.json"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


# ------------------------
# Cargar data
# ------------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


DATA = load_data()


# ------------------------
# Utilidades
# ------------------------

def parse_date(fecha):
    try:
        return datetime.strptime(fecha.strip(), "%d/%m/%Y")
    except Exception:
        return datetime.min


def normalize_text(t):
    t = t.lower()
    for s in ["ciones", "ción", "ar", "er", "ir", "o", "a"]:
        t = t.replace(s, "")
    return t


def is_listing_query(q):
    q = q.lower()
    triggers = [
        "que cortes", "qué cortes",
        "que notas", "qué notas",
        "cuáles", "cuales",
        "todas", "list"
    ]
    return any(t in q for t in triggers)
 
def detect_category(query):
    q = query.lower()

    categories = {
        "plenario": ["plenario", "consejo", "sesión"],
        "cortes": ["corte", "interrupción", "caída", "sistema", "eje", "portal"],
        "turnos": ["turno", "guardia", "feria"],
        "concursos": ["concurso", "designación", "terna", "juez", "jueza"],
        "obra_social": ["obra social", "afiliado", "cuota", "beneficio", "prestación"],
    }

    for cat, keys in categories.items():
        if any(k in q for k in keys):
            return cat

    return None


# ------------------------
# Construir contexto
# ------------------------

def build_context(query):
    q = query.lower()
    category = detect_category(query)
    words = [normalize_text(w) for w in q.split() if len(w) > 3]

    candidates = []

    for item in DATA:
    text = " ".join([
        str(item.get("titulo", "")),
        str(item.get("texto", "")),
        str(item.get("seccion", "")),
    ]).lower()

    # 🔥 filtro por categoría
    if category:
        if category == "plenario" and "plenario" not in text:
            continue
        if category == "cortes" and not any(k in text for k in ["corte", "eje", "portal"]):
            continue
        if category == "turnos" and "turno" not in text:
            continue
        if category == "concursos" and not any(k in text for k in ["concurso", "design"]):
            continue
        if category == "obra_social" and "obra social" not in text:
            continue

        text_n = normalize_text(text)

        score = sum(1 for w in words if w in text_n)

        if score > 0:
            candidates.append(item)

    if not candidates:
        return ""

    # 🔥 CASO ESPECIAL: "último plenario"
    if "plenario" in q and any(w in q for w in ["último", "reciente", "más nuevo"]):
        plenos = [c for c in candidates if "plenario" in (c.get("titulo","").lower() + c.get("texto","").lower())]

        plenos.sort(key=lambda x: parse_date(x.get("fecha","")), reverse=True)
        matches = plenos[:1]

    else:
        # ranking normal
        candidates.sort(key=lambda x: parse_date(x.get("fecha","")), reverse=True)
        limit = 50 if is_listing_query(query) else 8
        matches = candidates[:limit]

    parts = []
    for m in matches:
        parts.append(
            f"Título: {m.get('titulo')}\n"
            f"Fecha: {m.get('fecha')}\n"
            f"URL: {m.get('url')}\n"
            f"Contenido completo:\n{m.get('texto','')[:4000]}\n"
        )

    return "\n---\n".join(parts)




# ------------------------
# Rutas
# ------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/data")
def data():
    return jsonify(DATA)


# ------------------------
# Chat
# ------------------------

@app.route("/chat", methods=["POST"])
def chat():
    try:
        payload_json = request.get_json(silent=True) or {}
        print("JSON recibido:", payload_json)

        user_msg = (
            payload_json.get("text")
            or payload_json.get("question")
            or ""
        ).strip()

        if not user_msg:
            return jsonify({"answer": "Escribí una pregunta."})

        context = build_context(user_msg)

        if not context:
            return jsonify({"answer": "No se encontraron notas relacionadas con la consulta."})

        prompt = (
            "Respondé SOLO usando la información de las notas.\n"
            "Extraé los temas mencionados en el contenido, no solo el título.\n"
            "Listá todas las notas relevantes si la pregunta lo pide.\n"
            "Si no hay datos suficientes, decilo claramente.\n\n"
            f"{context}\n\n"
            f"Pregunta: {user_msg}"
        )

        payload = {
            "model": "gpt-4.1-mini",
            "messages": [
                {"role": "system", "content": "Respondé como asistente de intranet institucional."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }

        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )

        data = r.json()

        if "choices" not in data:
            return jsonify({"answer": "Error consultando el modelo.", "debug": data})

        answer = data["choices"][0]["message"]["content"]
        return jsonify({"answer": answer})

    except Exception as e:
        print("ERROR /chat:", e)
        return jsonify({"answer": "Error interno procesando la consulta."})


# ------------------------
# Run
# ------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
