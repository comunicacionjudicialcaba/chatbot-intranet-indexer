from flask import Flask, jsonify, request, render_template
import json, os, requests
from datetime import datetime

app = Flask(__name__)

DATA_FILE = "data.json"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# ------------------------
# DATA
# ------------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

DATA = load_data()

def parse_date(fecha):
    try:
        return datetime.strptime(fecha.strip(),"%d/%m/%Y")
    except:
        return datetime.min

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
    q = request.args.get("q","").lower()
    year = request.args.get("year","")
    tipo = request.args.get("tipo","")
    seccion = request.args.get("seccion","")

    res = []

    for n in DATA:
        text = " ".join([
            str(n.get("titulo","")),
            str(n.get("texto",""))
        ]).lower()

        if q and q not in text:
            continue

        if year and not n.get("fecha","").endswith(year):
            continue

        if tipo and n.get("tipo") != tipo:
            continue

        if seccion and n.get("seccion") != seccion:
            continue

        res.append(n)

    res.sort(key=lambda x: parse_date(x.get("fecha","")), reverse=True)
    return jsonify(res[:50])

# ------------------------
# CHAT
# ------------------------

@app.route("/chat", methods=["POST"])
def chat():
    payload = request.get_json(silent=True) or {}
    user_msg = payload.get("question","").strip()

    if not user_msg:
        return jsonify({"answer":"Escribí una pregunta."})

    context = "\n".join([
        f"{n.get('titulo')} | {n.get('fecha')} | {n.get('url')}"
        for n in DATA[:60]
    ])

    prompt = f"""
Usá solo esta información para responder:

{context}

Pregunta: {user_msg}
"""

    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type":"application/json"
        },
        json={
            "model":"gpt-4.1-mini",
            "messages":[
                {"role":"system","content":"Asistente institucional de intranet"},
                {"role":"user","content":prompt}
            ],
            "temperature":0.2
        },
        timeout=60
    )

    data = r.json()

    if "choices" not in data:
        return jsonify({"answer":"Error consultando modelo"})

    return jsonify({"answer": data["choices"][0]["message"]["content"]})

# ------------------------
# RUN
# ------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT",8080))
    app.run(host="0.0.0.0", port=port)
