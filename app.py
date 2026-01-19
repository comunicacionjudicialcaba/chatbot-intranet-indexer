from flask import Flask, jsonify, request, render_template
import json
import os
import requests

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
# Construir contexto
# ------------------------

def build_context(query, max_items=8):
    q = query.lower()

    matches = []
    for item in DATA:
        text = " ".join([
            str(item.get("titulo", "")),
            str(item.get("seccion", "")),
            str(item.get("autor", "")),
            str(item.get("fecha", "")),
        ]).lower()

        if q in text:
            matches.append(item)

    # priorizar más recientes si hay fecha
    def date_key(x):
        return x.get("fecha", "")

    matches = sorted(matches, key=date_key, reverse=True)
    matches = matches[:max_items]

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
    if not OPENAI_API_KEY:
        return jsonify({"answer": "ERROR: No hay API key configurada."}), 500

   user_msg = request.json.get("text", "").strip()


    if not user_msg:
        return jsonify({"answer": "Escribí una pregunta."})

    context = build_context(user_msg)

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

    try:
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
            return jsonify({"answer": "Error consultando OpenAI.", "debug": data}), 500

        answer = data["choices"][0]["message"]["content"]
        return jsonify({"answer": answer})

    except Exception as e:
        return jsonify({"answer": "Error interno del servidor.", "error": str(e)}), 500


# ------------------------
# Run
# ------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
