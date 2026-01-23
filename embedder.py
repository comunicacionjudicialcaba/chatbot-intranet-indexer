import json
import os
import time
import numpy as np
import requests

INPUT = "chunks.json"
VECTORS_OUT = "embeddings.npy"
META_OUT = "meta.json"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

MODEL = "text-embedding-3-small"

# -------------------------
# OPENAI EMBEDDING CALL
# -------------------------

def get_embedding(text):
    r = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Co
