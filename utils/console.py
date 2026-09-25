from __future__ import annotations
"""Consola de administración vía stdin (consola del panel tipo Pterodactyl).

El bot vive en UN solo servidor: el server_id es opcional en casi todo.
Listas con números: tras 'channels' o 'user', escribe el número para seleccionar.
"""
import asyncio
import datetime
import sys

import discord

_state = {"channel": None, "pending": None}  # pending = (kind, items)

BANNER = r"""
   _____             ___ ____        __
  / ___/____  __  __/ / / __ )____  / /_
  \__ \/ __ \/ / / / / / __  / __ \/ __/
 ___/ / /_/ / /_/ / / / /_/ / /_/ / /_
/____/\____/\__,_/_/_/_____/\____/\__/
        SoulBot Console v3 — escribe 'help'
"""

HELP_TEXT = """╭─ 📨 MENSAJES ─────────────────────────────╮
  say <texto>                 Hablar en el canal seleccionado
  say <canal_id> <texto>      Hablar en un canal concreto
  dm <usuario_id> <texto>     DM como SoulBot
╰─────────────────────────────────────────╯
╭─ 🔍 BUSCAR (listas con números) ─────────╮
  channels                    Todos los canales por categoría
  user <nombre>               Buscar gente (nombre o nick)
  roles                       Todos los roles con IDs
  userinfo <usuario_id>       Info de un usuario
  ↳ tras la lista, escribe el número para seleccionar
╰─────────────────────────────────────────╯
╭─ 🛡️ MODERACIÓN ────────────────────────────╮
  kick <user> [razón]         Expulsar
  ban <user> [razón]          Banear
  unban <user>                Desbanear
  timeout <user> <min> [razón]  Silenciar (0 quita)
  slowmode <canal> <seg>      Slowmode (0 quita)
  nick <user> <nick|none>     Cambiar apodo
  role <user> <add|del> <rol> Dar/quitar rol
  purge <canal> <cant>        Borrar últimos N (máx 100)
╰─────────────────────────────────────────╯
╭─ 💰 ECONOMÍA ─────────────────────────────╮
  coins <user>                Ver balance
  addcoins <user> <cant>      Dar/quitar (negativo quita)
╰─────────────────────────────────────────╯
╭─ ⚙️ SISTEMA ──────────────────────────────╮
  stats / servers / cogs / reload / sync
  snapshot                  Snapshot manual de niveles/coins
  dbstatus                  Estado de Turso ahora mismo
  clear / stop
╰──────────────────────────────────────────╯"""


def _out(msg: str = ""):
    print(msg, flush=True)


def _err(e: Exception):
    _out(f"❌ Error: {e}")


def _single_guild(bot) -> discord.Guild:
    if len(bot.guilds) == 1:
        return bot.guilds[0]
    raise ValueError("Varios servidores: pon el server_id primero")


def _strip_guild(bot, toks: list[str]):
    """Si el primer token es un server_id, lo consume. Si no, usa el único servidor."""
    if toks and toks[0].isdigit() and any(g.id == int(toks[0]) for g in bot.guilds):
        return bot.get_guild(int(toks[0])), toks[1:]
    return _single_guild(bot), toks


async def _resolve_channel(bot, cid: str):
    cid = int(cid)
    return bot.get_channel(cid) or await bot.fetch_channel(cid)


async def _member(g: discord.Guild, uid: str):
    m = g.get_member(int(uid))
    if m is None:
        m = await g.fetch_member(int(uid))
    return m


# ---------------- mensajes ----------------

async def _cmd_say(bot, args):
    if not args:
        _out("Uso: say <texto>  o  say <canal_id> <texto>")
        return
    raw = args[0]
    first, _, rest = raw.partition(" ")
    ch = None
    if rest and first.isdigit() and len(first) >= 15:
        try:
            ch = await _resolve_channel(bot, first)
            text = rest
        except Exception:
            ch = None
    if ch is None:
        if _state["channel"] is None:
            _out("❌ Indica canal (say <canal_id> <texto>) o selecciona uno con 'channels' + número.")
            return
        ch = _state["channel"]
        text = raw
    await ch.send(text)
    _out(f"✅ Enviado en #{getattr(ch, 'name', ch.id)}")


async def _cmd_dm(bot, args):
    if not args or " " not in args[0]:
        _out("Uso: dm <usuario_id> <texto>")
        return
    uid, _, text = args[0].partition(" ")
    u = bot.get_user(int(uid)) or await bot.fetch_user(int(uid))
    await u.send(text)
    _out(f"✅ DM enviado a {u}")


# ---------------- buscar ----------------

async def _cmd_channels(bot, args):
    g, rest = _strip_guild(bot, args)
    if rest:
        _out("Uso: channels")
        return
    cats: dict[str | None, list] = {}
    for ch in sorted(g.text_channels, key=lambda c: (c.category.position if c.category else -1, c.position)):
        cats.setdefault(ch.category.name if ch.category else "Sin categoría", []).append(ch)
    items = []
    _out(f"╭─ #{g.name} — canales ─")
    for cat, chs in cats.items():
        _out(f"│ 📁 {cat}")
        for ch in chs:
            items.append(ch)
            _out(f"│   [{len(items)}] #{ch.name}  |  ID {ch.id}")
    _out("╰" + "─" * 40)
    _state["pending"] = ("channel", items)
    _out("↳ Escribe el número para usar ese canal con 'say' (0 cancela)")


async def _cmd_user(bot, args):
    if not args:
        _out("Uso: user <nombre o nick>")
        return
    g, _ = _strip_guild(bot, [])
    q = " ".join(args).lower()
    found = [m for m in g.members
             if q in m.name.lower() or q in (m.nick or "").lower() or q in str(m).lower()]
    if not found:
        _out("🔎 No está en caché, buscando en Discord...")
        async for m in g.fetch_members(limit=None):
            if q in m.name.lower() or q in (m.nick or "").lower():
                found.append(m)
    if not found:
        _out(f"❌ Nadie parecido a '{q}'")
        return
    found = found[:15]
    _out(f"╭─ Coincidencias ({len(found)}) ─")
    for i, m in enumerate(found, 1):
        nick = f" | nick: {m.nick}" if m.nick else ""
        _out(f"│   [{i}] {m.name}{nick}  |  ID {m.id}")
    _out("╰" + "─" * 40)
    _state["pending"] = ("user", found)
    _out("↳ Escribe el número para ver ficha (0 cancela)")


async def _cmd_roles(bot, args):
    g, _ = _strip_guild(bot, args)
    _out(f"╭─ @{g.name} — roles ─")
    for r in sorted(g.roles, key=lambda r: r.position, reverse=True):
        if r.is_default():
            continue
        _out(f"│ @{r.name}  |  ID {r.id}  |  {len(r.members)} miembros")
    _out("╰" + "─" * 40)


async def _cmd_userinfo(bot, args):
    if len(args) != 1:
        _out("Uso: userinfo <usuario_id>")
        return
    uid = int(args[0])
    u = bot.get_user(uid) or await bot.fetch_user(uid)
    _out(f"👤 {u}  |  ID {u.id}  |  Bot: {'sí' if u.bot else 'no'}")
    _out(f"Avatar: {u.display_avatar.url}")


async def _show_user_detail(bot, m: discord.Member):
    import database as db
    bal = await db.get_balance(m.guild.id, m.id)
    roles = ", ".join(f"@{r.name}" for r in m.roles[1:][:5]) or "—"
    joined = m.joined_at.strftime("%d/%m/%Y") if m.joined_at else "?"
    _out("╭─ 👤 Ficha ─")
    _out(f"│ Nombre: {m.name}  |  Nick: {m.nick or '—'}  |  ID {m.id}")
    _out(f"│ Entró: {joined}  |  👛 {bal:,} SoulCoins".replace(",", "."))
    _out(f"│ Roles: {roles}")
    _out("╰" + "─" * 40)
    _out(f"↳ dm {m.id} <txt> · timeout {m.id} <min> · addcoins {m.id} <cant> · kick/ban {m.id}")


# ---------------- moderación ----------------

async def _cmd_kick(bot, args):
    toks = args[0].split(maxsplit=2) if args else []
    g, rest = _strip_guild(bot, toks)
    if not rest:
        _out("Uso: kick <usuario_id> [razón]")
        return
    m = await _member(g, rest[0])
    await m.kick(reason=" ".join(rest[1:]) if len(rest) > 1 else "Expulsado desde consola")
    _out(f"✅ {m} expulsado de {g.name}")


async def _cmd_ban(bot, args):
    toks = args[0].split(maxsplit=2) if args else []
    g, rest = _strip_guild(bot, toks)
    if not rest:
        _out("Uso: ban <usuario_id> [razón]")
        return
    await g.ban(discord.Object(id=int(rest[0])),
                reason=" ".join(rest[1:]) if len(rest) > 1 else "Baneado desde consola")
    _out(f"✅ {rest[0]} baneado de {g.name}")


async def _cmd_unban(bot, args):
    toks = args[0].split() if args else []
    g, rest = _strip_guild(bot, toks)
    if len(rest) != 1:
        _out("Uso: unban <usuario_id>")
        return
    await g.unban(discord.Object(id=int(rest[0])), reason="Desbaneo desde consola")
    _out(f"✅ {rest[0]} desbaneado de {g.name}")


async def _cmd_timeout(bot, args):
    toks = args[0].split(maxsplit=3) if args else []
    g, rest = _strip_guild(bot, toks)
    if len(rest) < 2:
        _out("Uso: timeout <usuario_id> <minutos> [razón]  (0 = quitar)")
        return
    m = await _member(g, rest[0])
    mins = int(rest[1])
    reason = rest[2] if len(rest) > 2 else "Timeout desde consola"
    until = None if mins <= 0 else discord.utils.utcnow() + datetime.timedelta(minutes=mins)
    await m.timeout(until, reason=reason)
    _out(f"✅ {'Timeout quitado a' if mins <= 0 else f'Silenciado {mins} min:'} {m}")


async def _cmd_slowmode(bot, args):
    if len(args) != 2:
        _out("Uso: slowmode <canal_id> <segundos>  (0 = quitar)")
        return
    ch = await _resolve_channel(bot, args[0])
    await ch.edit(slowmode_delay=int(args[1]))
    _out(f"✅ Slowmode de #{getattr(ch, 'name', args[0])}: {args[1]}s")


async def _cmd_nick(bot, args):
    toks = args[0].split(maxsplit=2) if args else []
    g, rest = _strip_guild(bot, toks)
    if len(rest) < 2:
        _out("Uso: nick <usuario_id> <nick|none>")
        return
    m = await _member(g, rest[0])
    nick = None if rest[1].lower() == "none" else rest[1]
    await m.edit(nick=nick, reason="Cambio desde consola")
    _out(f"✅ Apodo de {m}: {nick or '(reseteado)'}")


async def _cmd_role(bot, args):
    toks = args[0].split() if args else []
    g, rest = _strip_guild(bot, toks)
    if len(rest) != 3 or rest[1] not in ("add", "del"):
        _out("Uso: role <usuario_id> <add|del> <rol_id>")
        return
    m = await _member(g, rest[0])
    role = g.get_role(int(rest[2]))
    if role is None:
        raise ValueError(f"Rol {rest[2]} no existe")
    if rest[1] == "add":
        await m.add_roles(role, reason="Rol desde consola")
    else:
        await m.remove_roles(role, reason="Rol desde consola")
    _out(f"✅ @{role.name} {'→' if rest[1] == 'add' else '✕'} {m}")


async def _cmd_purge(bot, args):
    if len(args) != 2:
        _out("Uso: purge <canal_id> <cantidad>  (máx 100)")
        return
    ch = await _resolve_channel(bot, args[0])
    n = min(100, max(1, int(args[1])))
    deleted = await ch.purge(limit=n)
    _out(f"✅ {len(deleted)} borrados en #{getattr(ch, 'name', args[0])}")


# ---------------- economía ----------------

async def _cmd_coins(bot, args):
    toks = args[0].split() if args else []
    g, rest = _strip_guild(bot, toks)
    if len(rest) != 1:
        _out("Uso: coins <usuario_id>")
        return
    import database as db
    bal = await db.get_balance(g.id, int(rest[0]))
    _out(f"👛 Balance de {rest[0]}: **{bal:,}** SoulCoins".replace(",", "."))


async def _cmd_addcoins(bot, args):
    toks = args[0].split() if args else []
    g, rest = _strip_guild(bot, toks)
    if len(rest) != 2:
        _out("Uso: addcoins <usuario_id> <cantidad>")
        return
    import database as db
    new_bal = await db.add_coins(g.id, int(rest[0]), int(rest[1]), reason="Ajuste desde consola")
    _out(f"✅ Nuevo balance de {rest[0]}: **{new_bal:,}** SoulCoins".replace(",", "."))


# ---------------- sistema ----------------

async def _cmd_stats(bot, args):
    import database as db
    g = bot.guilds[0] if len(bot.guilds) == 1 else None
    uptime = datetime.datetime.now(datetime.timezone.utc) - bot._console_start
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    users = sum(x.member_count or 0 for x in bot.guilds)
    bots = sum(1 for x in bot.guilds for mb in x.members if mb.bot) if g else "?"
    text_ch = sum(len(x.text_channels) for x in bot.guilds)
    voice_ch = sum(len(x.voice_channels) for x in bot.guilds)
    total_coins = "?"
    if g:
        cur = await db.db().execute("SELECT COALESCE(SUM(balance),0) FROM economy WHERE guild_id=?", (g.id,))
        total_coins = f"{(await cur.fetchone())[0]:,}".replace(",", ".")
    import discord as _d
    _out("╭─ 📊 SoulBot Stats ─")
    _out(f"│ ⏱️ Uptime: {h}h {m}m {s}s  |  📶 {round(bot.latency * 1000)}ms")
    _out(f"│ 🏠 {g.name if g else f'{len(bot.guilds)} servidores'}  |  👥 {users} usuarios ({bots} bots)")
    _out(f"│ 💬 {text_ch} texto + 🔊 {voice_ch} voz  |  🎭 {len(g.roles) - 1 if g else '?'} roles")
    _out(f"│ 💰 En circulación: {total_coins} SoulCoins  |  🧩 {len(bot.cogs)} cogs")
    _out(f"│ 🐍 discord.py {_d.__version__}")
    _out("╰" + "─" * 40)


async def _cmd_servers(bot, args):
    if not bot.guilds:
        _out("(en ningún servidor todavía)")
        return
    for x in bot.guilds:
        _out(f" • {x.name}  |  ID {x.id}  |  {x.member_count} miembros")


async def _cmd_cogs(bot, args):
    _out("Cogs: " + ", ".join(sorted(bot.cogs)))


async def _cmd_reload(bot, args):
    if len(args) != 1:
        _out("Uso: reload <cog>  (ej: reload cogs.levels)")
        return
    await bot.reload_extension(args[0])
    _out(f"✅ {args[0]} recargado")


async def _cmd_sync(bot, args):
    if args:
        synced = await bot.tree.sync(guild=discord.Object(id=int(args[0])))
        _out(f"✅ {len(synced)} comandos en {args[0]}")
    else:
        synced = await bot.tree.sync()
        _out(f"✅ {len(synced)} comandos globales")


async def _cmd_snapshot(bot, args):
    import database as db
    import json as _json
    import os as _os
    from config import DATA_DIR as _DATA
    g = bot.guilds[0] if len(bot.guilds) == 1 else None
    if g is None:
        _out("Varios servidores: no soportado desde consola.")
        return
    data = await db.export_user_data(g.id)
    users = len(data.get("levels", []))
    ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    path = _os.path.join(_DATA, "backups", f"manual_users_{g.id}_{ts}.json")
    _os.makedirs(_os.path.dirname(path), exist_ok=True)

    def _write():
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)

    await asyncio.to_thread(_write)
    _out(f"✅ Snapshot guardado: {users} usuarios → {path}")


async def _cmd_dbstatus(bot, args):
    import database as db
    import time as _t
    mode = "Turso ☁️" if db.USING_TURSO else "SQLite local 💾"
    try:
        t = _t.perf_counter()
        cur = await db.db().execute("SELECT 1")
        await cur.fetchone()
        ms = round((_t.perf_counter() - t) * 1000)
        w = bot.get_cog("DbWatchCog")
        fails = getattr(w, "fails", 0) if w else 0
        down = getattr(w, "down", False) if w else False
        state = "🚨 CAÍDA" if down else "✅ OK"
        _out(f"💾 DB: {mode} | {state} | ping {ms}ms | fallos seguidos: {fails}")
    except Exception as e:
        _out(f"🚨 DB CAÍDA ({mode}): {e}")


COMMANDS = {
    "say": _cmd_say, "dm": _cmd_dm,
    "channels": _cmd_channels, "user": _cmd_user, "roles": _cmd_roles,
    "userinfo": _cmd_userinfo,
    "kick": _cmd_kick, "ban": _cmd_ban, "unban": _cmd_unban,
    "timeout": _cmd_timeout, "slowmode": _cmd_slowmode, "nick": _cmd_nick,
    "role": _cmd_role, "purge": _cmd_purge,
    "coins": _cmd_coins, "addcoins": _cmd_addcoins,
    "stats": _cmd_stats, "servers": _cmd_servers, "cogs": _cmd_cogs,
    "reload": _cmd_reload, "sync": _cmd_sync, "snapshot": _cmd_snapshot,
    "dbstatus": _cmd_dbstatus,
}


async def console_loop(bot):
    bot._console_start = datetime.datetime.now(datetime.timezone.utc)
    _out(BANNER)
    while True:
        try:
            print("SoulBot$ ", end="", flush=True)
            line = await asyncio.to_thread(sys.stdin.readline)
        except Exception:
            await asyncio.sleep(5)
            continue
        if not line:
            await asyncio.sleep(5)
            continue
        line = line.strip()
        if not line:
            continue

        # selección numérica pendiente (tras channels/user)
        if _state["pending"] and line.isdigit():
            kind, items = _state["pending"]
            n = int(line)
            _state["pending"] = None
            if n == 0:
                _out("Cancelado.")
                continue
            if 1 <= n <= len(items):
                if kind == "channel":
                    _state["channel"] = items[n - 1]
                    ch = items[n - 1]
                    _out(f"✅ Canal por defecto: #{ch.name} — ahora 'say <texto>' va ahí")
                else:
                    await _show_user_detail(bot, items[n - 1])
            else:
                _out("❌ Número fuera de rango.")
            continue
        _state["pending"] = None

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        raw = parts[1] if len(parts) > 1 else ""

        if cmd == "help":
            _out(HELP_TEXT)
        elif cmd == "clear":
            _out("\n" * 30 + "— consola limpia —")
        elif cmd == "stop":
            _out("Apagando SoulBot...")
            await bot.close()
            return
        elif cmd in COMMANDS:
            try:
                if cmd in ("say", "dm", "kick", "ban", "timeout", "nick", "role"):
                    call_args = [raw] if raw else []
                else:
                    call_args = raw.split() if raw else []
                await COMMANDS[cmd](bot, call_args)
            except Exception as e:
                _err(e)
        else:
            _out(f"❓ '{cmd}' no existe. Escribe 'help'.")
