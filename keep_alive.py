from __future__ import annotations
"""Servidor HTTP mínimo para UptimeRobot y para servir los transcripts de tickets en HTML."""
import os
from flask import Flask, send_from_directory, abort
from threading import Thread
from config import PORT, DATA_DIR

app = Flask(__name__)
TRANSCRIPTS_DIR = os.path.join(DATA_DIR, "transcripts")
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)


@app.route("/")
def home():
    return "SoulBot System está en línea. 🧠"


@app.route("/transcripts/<path:filename>")
def transcript(filename):
    if not filename.endswith(".html"):
        abort(404)
    return send_from_directory(TRANSCRIPTS_DIR, filename)


def run():
    app.run(host="0.0.0.0", port=PORT)


def keep_alive():
    Thread(target=run, daemon=True).start()
