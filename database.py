from __future__ import annotations
from typing import Optional
"""Capa de persistencia. Usa Turso (nube, persistente) si está configurado,
o SQLite local (aiosqlite) como fallback para desarrollo."""
import aiosqlite
from config import DB_PATH, TURSO_DATABASE_URL, TURSO_AUTH_TOKEN

_db = None
USING_TURSO = False


async def init_db():
    global _db, USING_TURSO
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        import turso_shim
        _db = await turso_shim.connect(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
        USING_TURSO = True
    else:
        _db = await aiosqlite.connect(DB_PATH)
        USING_TURSO = False
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

        CREATE TABLE IF NOT EXISTS economy (
            guild_id INTEGER,
            user_id INTEGER,
            balance INTEGER DEFAULT 0,
            last_daily TEXT,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            name TEXT,
            price INTEGER,
            type TEXT,
            role_id INTEGER,
            boost_multiplier REAL,
            boost_minutes INTEGER,
            xp_amount INTEGER,
            temprole_seconds INTEGER
        );

        CREATE TABLE IF NOT EXISTS economy_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS appeals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            sanction_id INTEGER,
            user_id INTEGER,
            reason TEXT,
            evidence_url TEXT,
            status TEXT DEFAULT 'pending',
            reviewed_by INTEGER,
            reviewed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS automod_warnings (
            guild_id INTEGER,
            user_id INTEGER,
            category TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id, category)
        );

        CREATE TABLE IF NOT EXISTS temp_roles (
            guild_id INTEGER,
            user_id INTEGER,
            role_id INTEGER,
            expires_at TEXT,
            assigned_by INTEGER,
            PRIMARY KEY (guild_id, user_id, role_id)
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
        "levels_enabled": "INTEGER DEFAULT 1",
        "appeals_channel_id": "INTEGER",
        "automod_spam": "INTEGER DEFAULT 1",
        "automod_flood": "INTEGER DEFAULT 1",
        "automod_caps": "INTEGER DEFAULT 1",
        "automod_ghostping": "INTEGER DEFAULT 1",
        "automod_ads": "INTEGER DEFAULT 1",
        "automod_warn_threshold": "INTEGER DEFAULT 2",
        "message_xp_min": "INTEGER DEFAULT 25",
        "message_xp_max": "INTEGER DEFAULT 75",
        "message_xp_cooldown": "INTEGER DEFAULT 30",
        "voice_xp_per_minute": "INTEGER DEFAULT 50",
        "daily_min": "INTEGER DEFAULT 100",
        "daily_max": "INTEGER DEFAULT 250",
        "levelup_coin_multiplier": "INTEGER DEFAULT 10",
        "game_win_reward": "INTEGER DEFAULT 40",
        "game_draw_reward": "INTEGER DEFAULT 10",
        "trivia_reward": "INTEGER DEFAULT 50",
    }
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            await _db.execute(f"ALTER TABLE guild_config ADD COLUMN {col} {col_type}")

    staff_cols = {row[1] for row in await (await _db.execute("PRAGMA table_info(staff_actions)")).fetchall()}
    if "evidence_url" not in staff_cols:
        await _db.execute("ALTER TABLE staff_actions ADD COLUMN evidence_url TEXT")
    if "infraction_key" not in staff_cols:
        await _db.execute("ALTER TABLE staff_actions ADD COLUMN infraction_key TEXT")

    shop_cols = {row[1] for row in await (await _db.execute("PRAGMA table_info(shop_items)")).fetchall()}
    if "xp_amount" not in shop_cols:
        await _db.execute("ALTER TABLE shop_items ADD COLUMN xp_amount INTEGER")
    if "temprole_seconds" not in shop_cols:
        await _db.execute("ALTER TABLE shop_items ADD COLUMN temprole_seconds INTEGER")

    tickets_cols = {row[1] for row in await (await _db.execute("PRAGMA table_info(tickets)")).fetchall()}
    if "claimed_at" not in tickets_cols:
        try:
            await _db.execute("ALTER TABLE tickets ADD COLUMN claimed_at TEXT")
        except Exception:
            pass
    if "last_activity" not in tickets_cols:
        try:
            await _db.execute("ALTER TABLE tickets ADD COLUMN last_activity TEXT DEFAULT CURRENT_TIMESTAMP")
            await _db.commit()
        except Exception:
            pass
        # No hacer UPDATE masivo en Turso en el mismo init (evita SQLITE_UNKNOWN si el column aún no es visible)
        # get_stale_tickets usa COALESCE(last_activity, created_at), así que NULL es válido
        try:
            await _db.execute("UPDATE tickets SET last_activity = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE last_activity IS NULL")
        except Exception:
            pass

    await _db.commit()


def db():
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
    reason: Optional[str] = None, evidence_url: Optional[str] = None, infraction_key: Optional[str] = None,
) -> int:
    cur = await _db.execute(
        "INSERT INTO staff_actions (guild_id, target_id, staff_id, action, reason, evidence_url, infraction_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (guild_id, target_id, staff_id, action, reason, evidence_url, infraction_key),
    )
    await _db.commit()
    return cur.lastrowid


async def decrement_infraction_count(guild_id: int, user_id: int, infraction_key: str):
    await _db.execute(
        "UPDATE infraction_counts SET count = MAX(count - 1, 0) WHERE guild_id = ? AND user_id = ? AND infraction_key = ?",
        (guild_id, user_id, infraction_key),
    )
    await _db.commit()


async def delete_staff_action(sanction_id: int):
    await _db.execute("DELETE FROM staff_actions WHERE id = ?", (sanction_id,))
    await _db.commit()


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
    try:
        cur = await _db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, category, last_activity) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (guild_id, channel_id, user_id, category),
        )
    except Exception as e:
        if "no column" in str(e).lower() and "last_activity" in str(e).lower():
            # fallback si la migración aún no ha llegado a Turso
            cur = await _db.execute(
                "INSERT INTO tickets (guild_id, channel_id, user_id, category) VALUES (?, ?, ?, ?)",
                (guild_id, channel_id, user_id, category),
            )
        else:
            raise
    await _db.commit()
    return cur.lastrowid


async def update_ticket_activity(channel_id: int):
    try:
        await _db.execute("UPDATE tickets SET last_activity = CURRENT_TIMESTAMP WHERE channel_id = ?", (channel_id,))
        await _db.commit()
    except Exception as e:
        if "no column" in str(e).lower() and "last_activity" in str(e).lower():
            # columna aún no existe en remoto — ignora, get_stale usa COALESCE
            return
        raise


async def get_stale_tickets(hours: int = 48) -> list[dict]:
    try:
        cur = await _db.execute(
            "SELECT * FROM tickets WHERE status='open' AND julianday('now') - julianday(COALESCE(last_activity, created_at)) > ? / 24.0",
            (hours,),
        )
    except Exception as e:
        if "no column" in str(e).lower() and "last_activity" in str(e).lower():
            cur = await _db.execute(
                "SELECT * FROM tickets WHERE status='open' AND julianday('now') - julianday(created_at) > ? / 24.0",
                (hours,),
            )
        else:
            raise
    rows = await cur.fetchall()
    cols = [d[0] for d in cur.description] if rows else []
    return [dict(zip(cols, r)) for r in rows]


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
    await _db.execute(
        "UPDATE tickets SET claimed_by = ?, claimed_at = CURRENT_TIMESTAMP WHERE channel_id = ?", (staff_id, channel_id)
    )
    await _db.commit()


async def get_ticket_stats(guild_id: int) -> dict:
    import datetime
    today = datetime.datetime.utcnow().date().isoformat()

    cur = await _db.execute("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'open'", (guild_id,))
    open_count = (await cur.fetchone())[0]

    cur = await _db.execute(
        "SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'closed' AND closed_at >= ?", (guild_id, today)
    )
    closed_today = (await cur.fetchone())[0]

    cur = await _db.execute(
        """SELECT AVG(julianday(claimed_at) - julianday(created_at)) * 24 * 60
           FROM tickets WHERE guild_id = ? AND claimed_at IS NOT NULL""",
        (guild_id,),
    )
    avg_claim_minutes = (await cur.fetchone())[0]

    cur = await _db.execute(
        """SELECT AVG(julianday(closed_at) - julianday(created_at)) * 24 * 60
           FROM tickets WHERE guild_id = ? AND closed_at IS NOT NULL""",
        (guild_id,),
    )
    avg_resolution_minutes = (await cur.fetchone())[0]

    cur = await _db.execute(
        """SELECT claimed_by, COUNT(*) FROM tickets WHERE guild_id = ? AND claimed_by IS NOT NULL
           GROUP BY claimed_by ORDER BY COUNT(*) DESC LIMIT 5""",
        (guild_id,),
    )
    top_staff = await cur.fetchall()

    return {
        "open": open_count,
        "closed_today": closed_today,
        "avg_claim_minutes": avg_claim_minutes,
        "avg_resolution_minutes": avg_resolution_minutes,
        "top_staff": top_staff,
    }


# ---------- cola de tickets ----------

async def add_to_queue(guild_id: int, user_id: int, category: str) -> int:
    cur = await _db.execute(
        "INSERT INTO ticket_queue (guild_id, user_id, category) VALUES (?, ?, ?)", (guild_id, user_id, category)
    )
    await _db.commit()
    return cur.lastrowid


async def get_queue_position(guild_id: int, entry_id: int) -> int:
    cur = await _db.execute(
        "SELECT COUNT(*) FROM ticket_queue WHERE guild_id = ? AND id <= ?", (guild_id, entry_id)
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


# ---------- economía (SoulCoins) ----------

async def get_balance(guild_id: int, user_id: int) -> int:
    cur = await _db.execute("SELECT balance FROM economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    row = await cur.fetchone()
    return row[0] if row else 0


async def add_coins(guild_id: int, user_id: int, amount: int, reason: str = "") -> int:
    """Suma (o resta si amount es negativo) SoulCoins. Nunca deja el balance por debajo de 0."""
    current = await get_balance(guild_id, user_id)
    new_balance = max(0, current + amount)
    await _db.execute(
        """INSERT INTO economy (guild_id, user_id, balance) VALUES (?, ?, ?)
           ON CONFLICT(guild_id, user_id) DO UPDATE SET balance = ?""",
        (guild_id, user_id, new_balance, new_balance),
    )
    await _db.execute(
        "INSERT INTO economy_transactions (guild_id, user_id, amount, reason) VALUES (?, ?, ?, ?)",
        (guild_id, user_id, amount, reason),
    )
    await _db.commit()
    return new_balance


async def set_balance(guild_id: int, user_id: int, amount: int):
    amount = max(0, amount)
    await _db.execute(
        """INSERT INTO economy (guild_id, user_id, balance) VALUES (?, ?, ?)
           ON CONFLICT(guild_id, user_id) DO UPDATE SET balance = ?""",
        (guild_id, user_id, amount, amount),
    )
    await _db.commit()


async def get_last_daily(guild_id: int, user_id: int) -> Optional[str]:
    cur = await _db.execute("SELECT last_daily FROM economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    row = await cur.fetchone()
    return row[0] if row else None


async def set_last_daily(guild_id: int, user_id: int, timestamp: str):
    await _db.execute(
        """INSERT INTO economy (guild_id, user_id, last_daily) VALUES (?, ?, ?)
           ON CONFLICT(guild_id, user_id) DO UPDATE SET last_daily = ?""",
        (guild_id, user_id, timestamp, timestamp),
    )
    await _db.commit()


async def get_economy_leaderboard(guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
    cur = await _db.execute(
        "SELECT user_id, balance FROM economy WHERE guild_id = ? ORDER BY balance DESC LIMIT ?", (guild_id, limit)
    )
    return await cur.fetchall()


# ---------- tienda ----------

async def add_shop_item(guild_id: int, name: str, price: int, item_type: str,
                         role_id: Optional[int] = None, boost_multiplier: Optional[float] = None,
                         boost_minutes: Optional[int] = None, xp_amount: Optional[int] = None,
                         temprole_seconds: Optional[int] = None) -> int:
    cur = await _db.execute(
        """INSERT INTO shop_items (guild_id, name, price, type, role_id, boost_multiplier, boost_minutes, xp_amount, temprole_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (guild_id, name, price, item_type, role_id, boost_multiplier, boost_minutes, xp_amount, temprole_seconds),
    )
    await _db.commit()
    return cur.lastrowid


async def get_shop_items(guild_id: int) -> list[dict]:
    cur = await _db.execute("SELECT * FROM shop_items WHERE guild_id = ? ORDER BY price", (guild_id,))
    rows = await cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in rows]


async def get_shop_item(guild_id: int, item_id: int) -> Optional[dict]:
    cur = await _db.execute("SELECT * FROM shop_items WHERE guild_id = ? AND id = ?", (guild_id, item_id))
    row = await cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


async def remove_shop_item(guild_id: int, item_id: int) -> bool:
    cur = await _db.execute("DELETE FROM shop_items WHERE guild_id = ? AND id = ?", (guild_id, item_id))
    await _db.commit()
    return cur.rowcount > 0 if hasattr(cur, "rowcount") else True


# ---------- appeals ----------

async def get_sanction_by_id(guild_id: int, sanction_id: int) -> Optional[dict]:
    cur = await _db.execute(
        "SELECT * FROM staff_actions WHERE guild_id = ? AND id = ?", (guild_id, sanction_id)
    )
    row = await cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


async def create_appeal(guild_id: int, sanction_id: int, user_id: int, reason: str, evidence_url: Optional[str]) -> int:
    cur = await _db.execute(
        "INSERT INTO appeals (guild_id, sanction_id, user_id, reason, evidence_url) VALUES (?, ?, ?, ?, ?)",
        (guild_id, sanction_id, user_id, reason, evidence_url),
    )
    await _db.commit()
    return cur.lastrowid


async def get_appeal(appeal_id: int) -> Optional[dict]:
    cur = await _db.execute("SELECT * FROM appeals WHERE id = ?", (appeal_id,))
    row = await cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


async def get_pending_appeal_for_sanction(guild_id: int, sanction_id: int) -> Optional[dict]:
    cur = await _db.execute(
        "SELECT * FROM appeals WHERE guild_id = ? AND sanction_id = ? AND status = 'pending'", (guild_id, sanction_id)
    )
    row = await cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


async def get_user_appeals(guild_id: int, user_id: int) -> list[dict]:
    cur = await _db.execute(
        "SELECT * FROM appeals WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC", (guild_id, user_id)
    )
    rows = await cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in rows]


async def resolve_appeal(appeal_id: int, status: str, reviewed_by: int):
    await _db.execute(
        "UPDATE appeals SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, reviewed_by, appeal_id),
    )
    await _db.commit()


# ---------- backups (config del servidor, no historial transaccional) ----------

async def export_guild_data(guild_id: int) -> dict:
    config = await get_guild_config(guild_id)
    rewards_cur = await _db.execute("SELECT level, role_id FROM level_rewards WHERE guild_id = ?", (guild_id,))
    rewards = await rewards_cur.fetchall()
    shop_cur = await _db.execute(
        "SELECT name, price, type, role_id, boost_multiplier, boost_minutes FROM shop_items WHERE guild_id = ?",
        (guild_id,),
    )
    shop = await shop_cur.fetchall()

    return {
        "guild_config": dict(config),
        "level_rewards": [{"level": r[0], "role_id": r[1]} for r in rewards],
        "shop_items": [
            {"name": s[0], "price": s[1], "type": s[2], "role_id": s[3], "boost_multiplier": s[4], "boost_minutes": s[5]}
            for s in shop
        ],
    }


async def import_guild_data(guild_id: int, data: dict):
    config = dict(data.get("guild_config", {}))
    config.pop("guild_id", None)
    if config:
        await update_guild_config(guild_id, **config)

    for reward in data.get("level_rewards", []):
        await add_level_reward(guild_id, reward["level"], reward["role_id"])

    for item in data.get("shop_items", []):
        await add_shop_item(
            guild_id, item["name"], item["price"], item["type"],
            role_id=item.get("role_id"), boost_multiplier=item.get("boost_multiplier"), boost_minutes=item.get("boost_minutes"),
        )


# ---------- roles temporales ----------

async def add_temp_role(guild_id: int, user_id: int, role_id: int, expires_at: str, assigned_by: int):
    await _db.execute(
        """INSERT INTO temp_roles (guild_id, user_id, role_id, expires_at, assigned_by) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(guild_id, user_id, role_id) DO UPDATE SET expires_at = ?, assigned_by = ?""",
        (guild_id, user_id, role_id, expires_at, assigned_by, expires_at, assigned_by),
    )
    await _db.commit()


async def remove_temp_role_record(guild_id: int, user_id: int, role_id: int):
    await _db.execute(
        "DELETE FROM temp_roles WHERE guild_id = ? AND user_id = ? AND role_id = ?", (guild_id, user_id, role_id)
    )
    await _db.commit()


async def get_due_temp_roles() -> list[tuple[int, int, int]]:
    import datetime
    now = datetime.datetime.utcnow().isoformat()
    cur = await _db.execute("SELECT guild_id, user_id, role_id FROM temp_roles WHERE expires_at <= ?", (now,))
    return await cur.fetchall()


async def get_active_temp_roles(guild_id: int, user_id: int) -> list[tuple[int, str]]:
    cur = await _db.execute(
        "SELECT role_id, expires_at FROM temp_roles WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
    )
    return await cur.fetchall()


# ---------- avisos previos de AutoMod (antes de aplicar la sanción real) ----------

async def get_automod_warning_count(guild_id: int, user_id: int, category: str) -> int:
    cur = await _db.execute(
        "SELECT count FROM automod_warnings WHERE guild_id = ? AND user_id = ? AND category = ?",
        (guild_id, user_id, category),
    )
    row = await cur.fetchone()
    return row[0] if row else 0


async def increment_automod_warning(guild_id: int, user_id: int, category: str) -> int:
    await _db.execute(
        """INSERT INTO automod_warnings (guild_id, user_id, category, count) VALUES (?, ?, ?, 1)
           ON CONFLICT(guild_id, user_id, category) DO UPDATE SET count = count + 1""",
        (guild_id, user_id, category),
    )
    await _db.commit()
    return await get_automod_warning_count(guild_id, user_id, category)


async def reset_automod_warning(guild_id: int, user_id: int, category: str):
    await _db.execute(
        "DELETE FROM automod_warnings WHERE guild_id = ? AND user_id = ? AND category = ?",
        (guild_id, user_id, category),
    )
    await _db.commit()
