from flask import Flask, render_template, jsonify, request
import os
import json
import requests
from openai import OpenAI

app = Flask(__name__)

DATA_FILE = "data.json"
DATA_URL = "https://raw.githubusercontent.com/comunicacionjudicialcaba/chatbot-intranet-indexer/main/data.json"

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# =====================
# HOME
# =====================

@app.route("/")
def home():
    return render_template("index.html")

# =====================
# DATA
# =====================

@app.route("/data")
def data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))

    # fallback a GitHub
    r = requests.get(DATA_URL, timeout=10)
    return jsonify(r.json())

# =====================
# CHATBOT
# =====================

@app.route("/chat", methods=["POST"])
def chat():
    payload = request.get_json()
    question = payload.get("question", "").strip()

    if not question:
        return jsonify({"answer": "No recibí ninguna pregunta.", "links": []})

    # cargar datos
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = requests.get(DATA_URL, timeout=10).json()

    context = []
    links = []

    words = question.lower().split()

    for item in data:
        text = ""

        if item.get("tipo") == "sheet":
            text = f"{item.get('titulo','')} {item.get('seccion','')} {item.get('autor','')}"
        elif item.get("tipo") == "doc":
            text = item.get("texto", "")

        if any(w in text.lower() for w in words):
            context.append(text[:600])
            if item.get("url"):
                links.append(item["url"])

        if len(context) >= 6:
            break

    if not context:
        return jsonify({
            "answer": "No encontré información relacionada en la intranet.",
            "links": []
        })

    prompt = f"""
Respondé usando únicamente la información del contexto.
No inventes datos.
Si algo no está en el texto, decilo claramente.

CONTEXTO:
{"\n\n".join(context)}

PREGUNTA:
{question}
"""

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "Sos un asistente de comunicación institucional del Poder Judicial."},
            {"role": "user", "content": prompt}
        ]
    )

    answer = completion.choices[0].message.content

    return jsonify({
        "answer": answer,
        "links": list(set(links))[:5]
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
