"""
Capa de datos del Dashboard. Síncrona (Flask), habla con la MISMA base de
datos que el bot (Turso si está configurado, o el SQLite local del bot
para pruebas). No usa aiosqlite/turso_shim (esos son solo para el bot,
que es async) — aquí usamos el cliente 'libsql' directo en modo síncrono,
o el módulo estándar sqlite3 si no hay Turso.
"""
import os
import sqlite3

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
DB_PATH = os.getenv("DB_PATH", "soulbot.db")

_conn = None


def get_conn():
    global _conn
    if _conn is not None:
        return _conn
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        import libsql
        _conn = libsql.connect(database=TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
    else:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return _conn


def _safe_params(params: tuple) -> tuple:
    """Igual que en turso_shim.py: evita que libsql pierda precisión en IDs de Discord grandes."""
    return tuple(str(p) if isinstance(p, (int, bool)) else p for p in params)


def query(sql: str, params: tuple = ()) -> list:
    conn = get_conn()
    cur = conn.execute(sql, _safe_params(params))
    return cur.fetchall()


def query_one(sql: str, params: tuple = ()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()):
    conn = get_conn()
    conn.execute(sql, _safe_params(params))
    conn.commit()


def get_guild_config(guild_id: int) -> dict:
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", _safe_params((guild_id,)))
    conn.commit()
    cur = conn.execute("SELECT * FROM guild_config WHERE guild_id = ?", _safe_params((guild_id,)))
    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def update_guild_config(guild_id: int, **fields):
    get_guild_config(guild_id)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [guild_id]
    execute(f"UPDATE guild_config SET {set_clause} WHERE guild_id = ?", tuple(values))
