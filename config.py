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
