from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("DB_PATH", "soulbot.db")
PORT = int(os.getenv("PORT", 8080))

# Opcional: si se define, los comandos slash se sincronizan solo en este servidor
# (aparecen al instante en vez de tardar hasta 1 hora con la sync global)
GUILD_ID = os.getenv("GUILD_ID")
GUILD_ID = int(GUILD_ID) if GUILD_ID else None

BRAND = "SoulSeeker™ | All rights reserved."
BOT_NAME = "SoulBot System"
COLOR = 0x5865F2
COLOR_SUCCESS = 0x57F287
COLOR_ERROR = 0xED4245

# Carpeta persistente para guardar transcripts de tickets (en Render, apunta al disco montado)
DATA_DIR = os.getenv("DATA_DIR", "data")

# Contraseña de confirmación para /levels resetserver (cámbiala en producción vía variable de entorno)
RESET_PASSWORD = os.getenv("RESET_PASSWORD", "Chroma")

# URL pública del servicio (la de Render), usada para enlazar transcripts en HTML.
# Si no se define, se usa localhost (solo sirve en pruebas locales).
PUBLIC_URL = os.getenv("PUBLIC_URL", f"http://localhost:{PORT}")
