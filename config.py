from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("DB_PATH", "soulbot.db")

# Turso (SQLite-compatible en la nube). Si están definidas, se usa en vez del
# archivo local — necesario porque Render Free no persiste disco entre reinicios.
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
PORT = int(os.getenv("PORT", 8080))

# Opcional: si se define, los comandos slash se sincronizan solo en este servidor
# (aparecen al instante en vez de tardar hasta 1 hora con la sync global)
GUILD_ID = os.getenv("GUILD_ID")
GUILD_ID = int(GUILD_ID) if GUILD_ID else None

BRAND = "SoulSeeker™ | All rights reserved."
BOT_NAME = "SoulBot System"

# Paleta de color unificada
COLOR = 0x5865F2          # azul principal (Blurple)
COLOR_SUCCESS = 0x57F287   # verde
COLOR_ERROR = 0xED4245     # rojo
COLOR_WARNING = 0xFEE75C   # amarillo
COLOR_INFO = 0x5865F2      # info usa el mismo azul principal

# Carpeta persistente para guardar transcripts de tickets (en Render, apunta al disco montado)
DATA_DIR = os.getenv("DATA_DIR", "data")

# Contraseña de confirmación para /levels resetserver (cámbiala en producción vía variable de entorno)
RESET_PASSWORD = os.getenv("RESET_PASSWORD", "Chroma")

# URL pública del servicio (la de Render), usada para enlazar transcripts en HTML.
# Si no se define, se usa localhost (solo sirve en pruebas locales).
PUBLIC_URL = os.getenv("PUBLIC_URL", f"http://localhost:{PORT}")

# ---------------- Vinculacion Minecraft <-> Discord (/code) ----------------
# RCON del servidor de Minecraft (para aplicar roles con /role adduser)
# PRODUCCIÓN: Usa Tailscale (100.x.x.x) o WireGuard. Ej: RCON_HOST=100.64.12.5
# bore.pub / trycloudflare.com / localhost.run son SOLO para pruebas locales — van sin cifrado y la PASS viaja en claro.
RCON_HOST = os.getenv("RCON_HOST", "127.0.0.1")
RCON_PORT = int(os.getenv("RCON_PORT", "25575"))
RCON_PASS = os.getenv("RCON_PASS", "")
RCON_ALLOW_PUBLIC = os.getenv("RCON_ALLOW_PUBLIC", "0") == "1"  # pon 1 solo si sabes lo que haces

# Postgres de Soulguard (donde se guardan los codigos de vinculacion)
POSTGRES_URL = os.getenv("POSTGRES_URL", "")
POSTGRES_USER = os.getenv("POSTGRES_USER", "")
POSTGRES_PASS = os.getenv("POSTGRES_PASS", "")

# Mapa de roles: ID de rol de Discord -> rol de Minecraft (Soulrole)
DC_ROLE_TO_MC = {
    "1532828482445508608": "leyenda soulseeker",
    "1542266765130604554": "netherite",
    "1542266835179806870": "Diamante",
    "1542266869489078385": "hierro",
}
MC_ROLE_TO_DC = {v: k for k, v in DC_ROLE_TO_MC.items()}
