from flask import Flask, jsonify
import json
import os

app = Flask(__name__)

DATA_FILE = "data.json"

@app.route("/")
def home():
    return "Chatbot Intranet activo 🚀"

@app.route("/data")
def data():
    if not os.path.exists(DATA_FILE):
        return jsonify({"error": "data.json no existe aún"}), 404

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
