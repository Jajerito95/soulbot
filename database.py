from __future__ import annotations
from typing import Optional
"""Capa de persistencia - SQLite ligero (aiosqlite). Un archivo, esquema mínimo."""
import aiosqlite
from config import DB_PATH

_db: Optional[aiosqlite.Connection] = None


async def init_db():
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            welcome_enabled INTEGER DEFAULT 0,
            welcome_channel_id INTEGER,
            welcome_message TEXT,
            suggestion_channel_id INTEGER,
            auto_approve_votes INTEGER DEFAULT 0,
            auto_deny_votes INTEGER DEFAULT 0,
            logs_channel_id INTEGER,
            logs_members INTEGER DEFAULT 1,
            logs_moderation INTEGER DEFAULT 1,
            logs_messages INTEGER DEFAULT 1,
            logs_roles INTEGER DEFAULT 1,
            logs_channels INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS invites (
            guild_id INTEGER,
            user_id INTEGER,
            invited_count INTEGER DEFAULT 0,
            left_count INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS suggestions (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER,
            author_id INTEGER,
            content TEXT,
            status TEXT DEFAULT 'pending',
            yes_votes INTEGER DEFAULT 0,
            no_votes INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS suggestion_votes (
            message_id INTEGER,
            user_id INTEGER,
            vote TEXT,
            PRIMARY KEY (message_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS staff_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            target_id INTEGER,
            staff_id INTEGER,
            action TEXT,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Migración simple para bases de datos ya existentes (añade columnas nuevas si faltan)
    existing_cols = {row[1] for row in await (await _db.execute("PRAGMA table_info(guild_config)")).fetchall()}
    new_cols = {
        "logs_channel_id": "INTEGER",
        "logs_members": "INTEGER DEFAULT 1",
        "logs_moderation": "INTEGER DEFAULT 1",
        "logs_messages": "INTEGER DEFAULT 1",
        "logs_roles": "INTEGER DEFAULT 1",
        "logs_channels": "INTEGER DEFAULT 1",
    }
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            await _db.execute(f"ALTER TABLE guild_config ADD COLUMN {col} {col_type}")
    await _db.commit()


def db() -> aiosqlite.Connection:
    return _db


async def get_guild_config(guild_id: int) -> dict:
    cur = await _db.execute("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,))
    row = await cur.fetchone()
    if row is None:
        await _db.execute("INSERT INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        await _db.commit()
        return await get_guild_config(guild_id)
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


async def update_guild_config(guild_id: int, **fields):
    await get_guild_config(guild_id)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [guild_id]
    await _db.execute(f"UPDATE guild_config SET {set_clause} WHERE guild_id = ?", values)
    await _db.commit()


# ---------- votos de sugerencias (un voto por usuario) ----------

async def get_user_vote(message_id: int, user_id: int) -> Optional[str]:
    cur = await _db.execute(
        "SELECT vote FROM suggestion_votes WHERE message_id = ? AND user_id = ?",
        (message_id, user_id),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def set_user_vote(message_id: int, user_id: int, vote: str):
    await _db.execute(
        """INSERT INTO suggestion_votes (message_id, user_id, vote) VALUES (?, ?, ?)
           ON CONFLICT(message_id, user_id) DO UPDATE SET vote = ?""",
        (message_id, user_id, vote, vote),
    )
    await _db.commit()


# ---------- logs de staff (base para el futuro /sanction) ----------

async def log_staff_action(guild_id: int, target_id: int, staff_id: int, action: str, reason: Optional[str] = None) -> int:
    cur = await _db.execute(
        "INSERT INTO staff_actions (guild_id, target_id, staff_id, action, reason) VALUES (?, ?, ?, ?, ?)",
        (guild_id, target_id, staff_id, action, reason),
    )
    await _db.commit()
    return cur.lastrowid
