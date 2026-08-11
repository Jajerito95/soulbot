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

        CREATE TABLE IF NOT EXISTS infraction_counts (
            guild_id INTEGER,
            user_id INTEGER,
            infraction_key TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id, infraction_key)
        );

        CREATE TABLE IF NOT EXISTS temp_bans (
            guild_id INTEGER,
            user_id INTEGER,
            unban_at TEXT,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            user_id INTEGER,
            category TEXT,
            status TEXT DEFAULT 'open',
            claimed_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            closed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ticket_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            category TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS levels (
            guild_id INTEGER,
            user_id INTEGER,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS level_rewards (
            guild_id INTEGER,
            level INTEGER,
            role_id INTEGER,
            PRIMARY KEY (guild_id, level)
        );

        CREATE TABLE IF NOT EXISTS user_multipliers (
            guild_id INTEGER,
            user_id INTEGER,
            multiplier REAL,
            expires_at TEXT,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS xp_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            amount INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_cards (
            guild_id INTEGER,
            user_id INTEGER,
            color TEXT,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS import_jobs (
            guild_id INTEGER PRIMARY KEY,
            status TEXT DEFAULT 'idle',
            progress INTEGER DEFAULT 0,
            total INTEGER DEFAULT 0,
            started_by INTEGER,
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
        "automod_enabled": "INTEGER DEFAULT 0",
        "tickets_category_id": "INTEGER",
        "tickets_staff_role_id": "INTEGER",
        "tickets_panel_channel_id": "INTEGER",
        "tickets_log_channel_id": "INTEGER",
        "tickets_categories": 'TEXT DEFAULT \'[["Soporte","🎫"],["Reportes","🚨"],["Otro","❓"]]\'',
        "tickets_max_active": "INTEGER DEFAULT 15",
        "tickets_paused": "INTEGER DEFAULT 0",
        "xp_global_multiplier": "REAL DEFAULT 1.0",
        "xp_global_multiplier_expires": "TEXT",
        "xp_weekend_enabled": "INTEGER DEFAULT 0",
        "levels_announce_channel_id": "INTEGER",
    }
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            await _db.execute(f"ALTER TABLE guild_config ADD COLUMN {col} {col_type}")

    staff_cols = {row[1] for row in await (await _db.execute("PRAGMA table_info(staff_actions)")).fetchall()}
    if "evidence_url" not in staff_cols:
        await _db.execute("ALTER TABLE staff_actions ADD COLUMN evidence_url TEXT")

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

async def log_staff_action(
    guild_id: int, target_id: int, staff_id: int, action: str,
    reason: Optional[str] = None, evidence_url: Optional[str] = None,
) -> int:
    cur = await _db.execute(
        "INSERT INTO staff_actions (guild_id, target_id, staff_id, action, reason, evidence_url) VALUES (?, ?, ?, ?, ?, ?)",
        (guild_id, target_id, staff_id, action, reason, evidence_url),
    )
    await _db.commit()
    return cur.lastrowid


async def get_user_sanctions(guild_id: int, user_id: int) -> list[dict]:
    cur = await _db.execute(
        """SELECT id, staff_id, action, reason, evidence_url, created_at FROM staff_actions
           WHERE guild_id = ? AND target_id = ? AND action IN ('warn', 'ban', 'unban')
           ORDER BY created_at DESC""",
        (guild_id, user_id),
    )
    rows = await cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in rows]


# ---------- motor de sanciones automático (infracciones + bans temporales) ----------

async def get_infraction_count(guild_id: int, user_id: int, infraction_key: str) -> int:
    cur = await _db.execute(
        "SELECT count FROM infraction_counts WHERE guild_id = ? AND user_id = ? AND infraction_key = ?",
        (guild_id, user_id, infraction_key),
    )
    row = await cur.fetchone()
    return row[0] if row else 0


async def increment_infraction_count(guild_id: int, user_id: int, infraction_key: str):
    await _db.execute(
        """INSERT INTO infraction_counts (guild_id, user_id, infraction_key, count) VALUES (?, ?, ?, 1)
           ON CONFLICT(guild_id, user_id, infraction_key) DO UPDATE SET count = count + 1""",
        (guild_id, user_id, infraction_key),
    )
    await _db.commit()


async def add_temp_ban(guild_id: int, user_id: int, days: int):
    import datetime
    unban_at = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat()
    await _db.execute(
        """INSERT INTO temp_bans (guild_id, user_id, unban_at) VALUES (?, ?, ?)
           ON CONFLICT(guild_id, user_id) DO UPDATE SET unban_at = ?""",
        (guild_id, user_id, unban_at, unban_at),
    )
    await _db.commit()


async def get_due_temp_bans() -> list[tuple[int, int]]:
    import datetime
    now = datetime.datetime.utcnow().isoformat()
    cur = await _db.execute("SELECT guild_id, user_id FROM temp_bans WHERE unban_at <= ?", (now,))
    return await cur.fetchall()


async def remove_temp_ban(guild_id: int, user_id: int):
    await _db.execute("DELETE FROM temp_bans WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    await _db.commit()


# ---------- tickets ----------

async def create_ticket(guild_id: int, channel_id: int, user_id: int, category: str) -> int:
    cur = await _db.execute(
        "INSERT INTO tickets (guild_id, channel_id, user_id, category) VALUES (?, ?, ?, ?)",
        (guild_id, channel_id, user_id, category),
    )
    await _db.commit()
    return cur.lastrowid


async def get_ticket_by_channel(channel_id: int) -> Optional[dict]:
    cur = await _db.execute("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,))
    row = await cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


async def get_open_ticket_for_user(guild_id: int, user_id: int) -> Optional[dict]:
    cur = await _db.execute(
        "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'", (guild_id, user_id)
    )
    row = await cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


async def count_open_tickets(guild_id: int) -> int:
    cur = await _db.execute("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'open'", (guild_id,))
    row = await cur.fetchone()
    return row[0]


async def close_ticket(channel_id: int):
    await _db.execute(
        "UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE channel_id = ?", (channel_id,)
    )
    await _db.commit()


async def claim_ticket(channel_id: int, staff_id: int):
    await _db.execute("UPDATE tickets SET claimed_by = ? WHERE channel_id = ?", (staff_id, channel_id))
    await _db.commit()


# ---------- cola de tickets ----------

async def add_to_queue(guild_id: int, user_id: int, category: str) -> int:
    cur = await _db.execute(
        "INSERT INTO ticket_queue (guild_id, user_id, category) VALUES (?, ?, ?)", (guild_id, user_id, category)
    )
    await _db.commit()
    return cur.lastrowid


async def get_queue_position(guild_id: int, entry_id: int) -> int:
    cur = await _db.execute(
        "SELECT COUNT(*) FROM ticket_queue WHERE guild_id = ? AND id <= ? ORDER BY id", (guild_id, entry_id)
    )
    row = await cur.fetchone()
    return row[0]


async def pop_queue(guild_id: int) -> Optional[dict]:
    cur = await _db.execute(
        "SELECT * FROM ticket_queue WHERE guild_id = ? ORDER BY id LIMIT 1", (guild_id,)
    )
    row = await cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    entry = dict(zip(cols, row))
    await _db.execute("DELETE FROM ticket_queue WHERE id = ?", (entry["id"],))
    await _db.commit()
    return entry


# ---------- niveles ----------

async def get_level_data(guild_id: int, user_id: int) -> dict:
    cur = await _db.execute("SELECT xp, level FROM levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    row = await cur.fetchone()
    if not row:
        return {"xp": 0, "level": 0}
    return {"xp": row[0], "level": row[1]}


async def set_level_data(guild_id: int, user_id: int, xp: int, level: int):
    await _db.execute(
        """INSERT INTO levels (guild_id, user_id, xp, level) VALUES (?, ?, ?, ?)
           ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?, level = ?""",
        (guild_id, user_id, xp, level, xp, level),
    )
    await _db.commit()


async def log_xp_event(guild_id: int, user_id: int, amount: int):
    await _db.execute(
        "INSERT INTO xp_events (guild_id, user_id, amount) VALUES (?, ?, ?)", (guild_id, user_id, amount)
    )
    await _db.commit()


async def get_xp_gained_since(guild_id: int, user_id: int, days: int) -> int:
    import datetime
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    cur = await _db.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM xp_events WHERE guild_id = ? AND user_id = ? AND created_at >= ?",
        (guild_id, user_id, cutoff),
    )
    row = await cur.fetchone()
    return row[0]


async def get_leaderboard_alltime(guild_id: int, limit: int = 10) -> list[tuple[int, int, int]]:
    cur = await _db.execute(
        "SELECT user_id, xp, level FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?", (guild_id, limit)
    )
    return await cur.fetchall()


async def get_leaderboard_period(guild_id: int, days: int, limit: int = 10) -> list[tuple[int, int]]:
    import datetime
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    cur = await _db.execute(
        """SELECT user_id, SUM(amount) as total FROM xp_events
           WHERE guild_id = ? AND created_at >= ? GROUP BY user_id ORDER BY total DESC LIMIT ?""",
        (guild_id, cutoff, limit),
    )
    return await cur.fetchall()


async def add_level_reward(guild_id: int, level: int, role_id: int):
    await _db.execute(
        """INSERT INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?)
           ON CONFLICT(guild_id, level) DO UPDATE SET role_id = ?""",
        (guild_id, level, role_id, role_id),
    )
    await _db.commit()


async def get_level_rewards(guild_id: int) -> list[tuple[int, int]]:
    cur = await _db.execute("SELECT level, role_id FROM level_rewards WHERE guild_id = ? ORDER BY level", (guild_id,))
    return await cur.fetchall()


async def get_user_multiplier(guild_id: int, user_id: int) -> Optional[tuple[float, Optional[str]]]:
    cur = await _db.execute(
        "SELECT multiplier, expires_at FROM user_multipliers WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
    )
    row = await cur.fetchone()
    return tuple(row) if row else None


async def set_user_multiplier(guild_id: int, user_id: int, multiplier: float, expires_at: Optional[str]):
    await _db.execute(
        """INSERT INTO user_multipliers (guild_id, user_id, multiplier, expires_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(guild_id, user_id) DO UPDATE SET multiplier = ?, expires_at = ?""",
        (guild_id, user_id, multiplier, expires_at, multiplier, expires_at),
    )
    await _db.commit()


async def get_card_color(guild_id: int, user_id: int) -> Optional[str]:
    cur = await _db.execute("SELECT color FROM user_cards WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    row = await cur.fetchone()
    return row[0] if row else None


async def set_card_color(guild_id: int, user_id: int, color: str):
    await _db.execute(
        """INSERT INTO user_cards (guild_id, user_id, color) VALUES (?, ?, ?)
           ON CONFLICT(guild_id, user_id) DO UPDATE SET color = ?""",
        (guild_id, user_id, color, color),
    )
    await _db.commit()


async def reset_member_levels(guild_id: int, user_id: int):
    await _db.execute("DELETE FROM levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    await _db.execute("DELETE FROM xp_events WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    await _db.commit()


async def reset_server_levels(guild_id: int):
    await _db.execute("DELETE FROM levels WHERE guild_id = ?", (guild_id,))
    await _db.execute("DELETE FROM xp_events WHERE guild_id = ?", (guild_id,))
    await _db.commit()


# ---------- import de niveles (Arcane u otra fuente externa) ----------

async def create_import_job(guild_id: int, started_by: int, total: int):
    await _db.execute(
        """INSERT INTO import_jobs (guild_id, status, progress, total, started_by) VALUES (?, 'running', 0, ?, ?)
           ON CONFLICT(guild_id) DO UPDATE SET status = 'running', progress = 0, total = ?, started_by = ?""",
        (guild_id, total, started_by, total, started_by),
    )
    await _db.commit()


async def get_import_job(guild_id: int) -> Optional[dict]:
    cur = await _db.execute("SELECT * FROM import_jobs WHERE guild_id = ?", (guild_id,))
    row = await cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


async def update_import_progress(guild_id: int, progress: int):
    await _db.execute("UPDATE import_jobs SET progress = ? WHERE guild_id = ?", (progress, guild_id))
    await _db.commit()


async def set_import_status(guild_id: int, status: str):
    await _db.execute("UPDATE import_jobs SET status = ? WHERE guild_id = ?", (status, guild_id))
    await _db.commit()
