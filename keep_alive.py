from __future__ import annotations
"""Servidor HTTP mínimo para que UptimeRobot mantenga el bot despierto en Render."""
from flask import Flask
from threading import Thread
from config import PORT

app = Flask(__name__)


@app.route("/")
def home():
    return "SoulBot System está en línea. 🧠"


def run():
    app.run(host="0.0.0.0", port=PORT)


def keep_alive():
    Thread(target=run, daemon=True).start()
