from flask import Flask, jsonify, request, render_template
import json
import os
import requests
from datetime import datetime

app = Flask(__name__)

DATA_FILE = "data.json"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


# ------------------------
# Cargar data.json
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
        "que cortes", "qué cortes", "list", "todas",
        "que notas", "qué notas", "cuáles", "cuales"
    ]
    return any(t in q for t in triggers)


# ------------------------
# Construir contexto
# ------------------------

def is_listing_query(q):
    q = q.lower()
    triggers = [
        "que cortes", "qué cortes", "list", "todas",
        "que notas", "qué notas", "cuáles", "cuales"
    ]
    return any(t in q for t in triggers)
def build_context(query, max_items=8):

    words = [normalize_text(w) for w in query.lower().split() if len(w) > 3]

    scored = []

    for item in DATA:
        text = " ".join([
            str(item.get("titulo", "")),
            str(item.get("seccion", "")),
            str(item.get("autor", "")),
            str(item.get("fecha", "")),
        ])

        text_n = normalize_text(text)

        score = sum(1 for w in words if w in text_n)

        if score > 0:
            scored.append((score, item))

    scored.sort(
        key=lambda x: (x[0], parse_date(x[1].get("fecha", ""))),
        reverse=True
    )

    limit = 50 if is_listing_query(query) else 8
matches = [item for _, item in scored[:limit]]

    parts = []
    for m in matches:
        parts.append(
            f"Título: {m.get('titulo')}\n"
            f"Fecha: {m.get('fecha')}\n"
            f"Autor: {m.get('autor')}\n"
            f"Sección: {m.get('seccion')}\n"
            f"URL: {m.get('url')}\n"
        )

    return "\n---\n".join(parts)


# ------------------------
# Rutas web
# ------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/data")
def data():
    return jsonify(DATA)


# ------------------------
# Chatbot
# ------------------------

@app.route("/chat", methods=["POST"])
def chat():
    try:
        payload_json = request.get_json(silent=True) or {}

        # TU FRONTEND USA "question"
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
            "Usá únicamente la información siguiente para responder.\n"
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
