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

def safe(v):
    return v if v not in [None, "", "null"] else ""

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
    payload = request.get_json(silent=True) or {}
    user_msg = payload.get("question","").strip()

    if not user_msg:
        return jsonify({"answer":"Escribí una pregunta."})

    context_parts = []

    for n in sorted(DATA, key=lambda x: parse_date(x.get("fecha","")), reverse=True)[:80]:
        context_parts.append(
            f"Título: {safe(n.get('titulo'))}\n"
            f"Fecha: {safe(n.get('fecha'))}\n"
            f"URL: {safe(n.get('url'))}\n"
            f"Texto: {safe(n.get('texto'))[:2000]}\n"
        )

    context = "\n---\n".join(context_parts)

    prompt = f"""
Usá únicamente la información de las notas para responder.
Si hay más de una nota relevante, mencioná todas con su link.
Si no hay datos suficientes, decilo claramente.

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
