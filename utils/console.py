from __future__ import annotations
"""Consola de administración vía stdin (consola del panel tipo Pterodactyl)."""
import asyncio
import datetime
import sys

import discord

BANNER = r"""
   _____             ___ ____        __
  / ___/____  __  __/ / / __ )____  / /_
  \__ \/ __ \/ / / / / / __  / __ \/ __/
 ___/ / /_/ / /_/ / / / /_/ / /_/ / /_
/____/\____/\__,_/_/_/_____/\____/\__/
        SoulBot Console v2 — escribe 'help'
"""

HELP_TEXT = """╭─ 📨 MENSAJES ─────────────────────────────╮
  say <canal_id> <texto>      Hablar como SoulBot
  embed <canal_id> <título> | <texto>   Enviar embed
  dm <usuario_id> <texto>     DM como SoulBot
╰─────────────────────────────────────────╯
╭─ 🖥️ SERVIDORES ────────────────────────────╮
  servers                     Lista servidores
  channels <server_id>        Canales de texto (con IDs)
  userinfo <usuario_id>       Info de un usuario
╰─────────────────────────────────────────╯
╭─ 🛡️ MODERACIÓN ────────────────────────────╮
  kick <server> <user> [razón]   Expulsar
  ban <server> <user> [razón]    Banear
  unban <server> <user>          Desbanear
  timeout <server> <user> <min> [razón]  Silenciar X min (0 quita)
  slowmode <canal> <seg>         Slowmode (0 quita)
  nick <server> <user> <nick|none>  Cambiar apodo
  role <server> <user> <add|del> <rol_id>  Dar/quitar rol
  purge <canal> <cant>           Borrar últimos N msgs (máx 100)
╰─────────────────────────────────────────╯
╭─ 💰 ECONOMÍA ─────────────────────────────╮
  coins <server> <user>       Ver balance
  addcoins <server> <user> <cant>  Dar/quitar coins (negativo quita)
╰─────────────────────────────────────────╯
╭─ ⚙️ SISTEMA ──────────────────────────────╮
  stats                       Uptime, latencia, servidores
  cogs                        Cogs cargados
  reload <cog>                Recargar cog (ej: reload cogs.levels)
  sync [server_id]            Re-sincronizar comandos slash
  clear                       Limpiar consola (separador)
  stop                        Apagar el bot
╰──────────────────────────────────────────╯"""


def _out(msg: str = ""):
    print(msg, flush=True)


def _err(e: Exception):
    _out(f"❌ Error: {e}")


async def _resolve_channel(bot, cid: str):
    cid = int(cid)
    return bot.get_channel(cid) or await bot.fetch_channel(cid)


async def _resolve_guild(bot, gid: str):
    gid = int(gid)
    g = bot.get_guild(gid)
    if g is None:
        raise ValueError(f"No estoy en el servidor {gid}")
    return g


async def _cmd_servers(bot, args):
    if not bot.guilds:
        _out("(en ningún servidor todavía)")
        return
    _out(f"╭─ Servidores ({len(bot.guilds)}) ─")
    for g in bot.guilds:
        _out(f"│ {g.name}  |  ID {g.id}  |  {g.member_count} miembros")
    _out("╰" + "─" * 40)


async def _cmd_channels(bot, args):
    if len(args) != 1:
        _out("Uso: channels <server_id>")
        return
    g = await _resolve_guild(bot, args[0])
    _out(f"╭─ #{g.name} — canales de texto ─")
    for ch in sorted(g.text_channels, key=lambda c: c.position):
        _out(f"│ #{ch.name}  |  ID {ch.id}")
    _out("╰" + "─" * 40)


async def _cmd_userinfo(bot, args):
    if len(args) != 1:
        _out("Uso: userinfo <usuario_id>")
        return
    uid = int(args[0])
    u = bot.get_user(uid) or await bot.fetch_user(uid)
    _out(f"👤 {u}  |  ID {u.id}  |  Bot: {'sí' if u.bot else 'no'}")
    _out(f"Avatar: {u.display_avatar.url}")


async def _cmd_say(bot, args):
    if len(args) < 2:
        _out("Uso: say <canal_id> <texto>")
        return
    ch = await _resolve_channel(bot, args[0])
    await ch.send(args[1])
    _out(f"✅ Enviado en #{getattr(ch, 'name', args[0])}")


async def _cmd_embed(bot, args):
    if len(args) < 2 or "|" not in args[1]:
        _out("Uso: embed <canal_id> <título> | <texto>")
        return
    title, _, text = args[1].partition("|")
    ch = await _resolve_channel(bot, args[0])
    from utils.embeds import base_embed
    from config import COLOR
    await ch.send(embed=base_embed(text.strip(), COLOR, title=title.strip()))
    _out(f"✅ Embed enviado en #{getattr(ch, 'name', args[0])}")


async def _cmd_dm(bot, args):
    if len(args) < 2:
        _out("Uso: dm <usuario_id> <texto>")
        return
    u = bot.get_user(int(args[0])) or await bot.fetch_user(int(args[0]))
    await u.send(args[1])
    _out(f"✅ DM enviado a {u}")


async def _cmd_kick(bot, args):
    if len(args) < 2:
        _out("Uso: kick <server_id> <usuario_id> [razón]")
        return
    g = await _resolve_guild(bot, args[0])
    reason = args[2] if len(args) > 2 else "Expulsado desde consola"
    await g.kick(discord.Object(id=int(args[1])), reason=reason)
    _out(f"✅ {args[1]} expulsado de {g.name}")


async def _cmd_ban(bot, args):
    if len(args) < 2:
        _out("Uso: ban <server_id> <usuario_id> [razón]")
        return
    g = await _resolve_guild(bot, args[0])
    reason = args[2] if len(args) > 2 else "Baneado desde consola"
    await g.ban(discord.Object(id=int(args[1])), reason=reason)
    _out(f"✅ {args[1]} baneado de {g.name}")


async def _cmd_unban(bot, args):
    if len(args) != 2:
        _out("Uso: unban <server_id> <usuario_id>")
        return
    g = await _resolve_guild(bot, args[0])
    await g.unban(discord.Object(id=int(args[1])), reason="Desbaneo desde consola")
    _out(f"✅ {args[1]} desbaneado de {g.name}")


async def _member(bot, gid: str, uid: str):
    g = await _resolve_guild(bot, gid)
    m = g.get_member(int(uid))
    if m is None:
        m = await g.fetch_member(int(uid))
    return g, m


async def _cmd_timeout(bot, args):
    if len(args) < 3:
        _out("Uso: timeout <server_id> <usuario_id> <minutos> [razón]  (0 = quitar)")
        return
    g, m = await _member(bot, args[0], args[1])
    mins = int(args[2])
    reason = args[3] if len(args) > 3 else "Timeout desde consola"
    until = None if mins <= 0 else discord.utils.utcnow() + datetime.timedelta(minutes=mins)
    await m.timeout(until, reason=reason)
    _out(f"✅ {'Timeout quitado a' if mins <= 0 else f'Silenciado {mins} min:'} {m} en {g.name}")


async def _cmd_slowmode(bot, args):
    if len(args) != 2:
        _out("Uso: slowmode <canal_id> <segundos>  (0 = quitar)")
        return
    ch = await _resolve_channel(bot, args[0])
    await ch.edit(slowmode_delay=int(args[1]))
    _out(f"✅ Slowmode de #{getattr(ch, 'name', args[0])}: {args[1]}s")


async def _cmd_nick(bot, args):
    if len(args) < 3:
        _out("Uso: nick <server_id> <usuario_id> <nick|none>")
        return
    g, m = await _member(bot, args[0], args[1])
    nick = None if args[2].lower() == "none" else args[2]
    await m.edit(nick=nick, reason="Cambio desde consola")
    _out(f"✅ Apodo de {m}: {nick or '(reseteado)'}")


async def _cmd_role(bot, args):
    if len(args) != 4 or args[2] not in ("add", "del"):
        _out("Uso: role <server_id> <usuario_id> <add|del> <rol_id>")
        return
    g, m = await _member(bot, args[0], args[1])
    role = g.get_role(int(args[3]))
    if role is None:
        raise ValueError(f"Rol {args[3]} no existe en {g.name}")
    if args[2] == "add":
        await m.add_roles(role, reason="Rol desde consola")
    else:
        await m.remove_roles(role, reason="Rol desde consola")
    _out(f"✅ Rol @{role.name} {'dado a' if args[2] == 'add' else 'quitado a'} {m}")


async def _cmd_purge(bot, args):
    if len(args) != 2:
        _out("Uso: purge <canal_id> <cantidad>  (máx 100)")
        return
    ch = await _resolve_channel(bot, args[0])
    n = min(100, max(1, int(args[1])))
    deleted = await ch.purge(limit=n)
    _out(f"✅ {len(deleted)} mensajes borrados en #{getattr(ch, 'name', args[0])}")


async def _cmd_coins(bot, args):
    if len(args) != 2:
        _out("Uso: coins <server_id> <usuario_id>")
        return
    import database as db
    bal = await db.get_balance(int(args[0]), int(args[1]))
    _out(f"👛 Balance de {args[1]}: **{bal:,}** SoulCoins".replace(",", "."))


async def _cmd_addcoins(bot, args):
    if len(args) != 3:
        _out("Uso: addcoins <server_id> <usuario_id> <cantidad>")
        return
    import database as db
    new_bal = await db.add_coins(int(args[0]), int(args[1]), int(args[2]), reason="Ajuste desde consola")
    _out(f"✅ Nuevo balance de {args[1]}: **{new_bal:,}** SoulCoins".replace(",", "."))


async def _cmd_stats(bot, args):
    uptime = datetime.datetime.now(datetime.timezone.utc) - bot._console_start
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    users = sum(g.member_count or 0 for g in bot.guilds)
    _out("╭─ 📊 Stats ─")
    _out(f"│ ⏱️ Uptime: {h}h {m}m {s}s")
    _out(f"│ 📶 Latencia: {round(bot.latency * 1000)}ms")
    _out(f"│ 🏠 Servidores: {len(bot.guilds)}  |  👥 Usuarios: {users}")
    _out("╰" + "─" * 40)


async def _cmd_cogs(bot, args):
    _out("Cogs cargados:")
    for name in sorted(bot.cogs):
        _out(f"  • {name}")


async def _cmd_reload(bot, args):
    if len(args) != 1:
        _out("Uso: reload <cog>  (ej: reload cogs.levels)")
        return
    await bot.reload_extension(args[0])
    _out(f"✅ {args[0]} recargado")


async def _cmd_sync(bot, args):
    if args:
        g = discord.Object(id=int(args[0]))
        synced = await bot.tree.sync(guild=g)
        _out(f"✅ {len(synced)} comandos en servidor {args[0]}")
    else:
        synced = await bot.tree.sync()
        _out(f"✅ {len(synced)} comandos globales")


COMMANDS = {
    "servers": _cmd_servers,
    "channels": _cmd_channels,
    "userinfo": _cmd_userinfo,
    "say": _cmd_say,
    "embed": _cmd_embed,
    "dm": _cmd_dm,
    "kick": _cmd_kick,
    "ban": _cmd_ban,
    "unban": _cmd_unban,
    "timeout": _cmd_timeout,
    "slowmode": _cmd_slowmode,
    "nick": _cmd_nick,
    "role": _cmd_role,
    "purge": _cmd_purge,
    "coins": _cmd_coins,
    "addcoins": _cmd_addcoins,
    "stats": _cmd_stats,
    "cogs": _cmd_cogs,
    "reload": _cmd_reload,
    "sync": _cmd_sync,
}


async def console_loop(bot):
    import datetime as _dt
    bot._console_start = _dt.datetime.now(_dt.timezone.utc)
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
        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()
        raw_args = line.split(maxsplit=1)[1] if " " in line else ""

        if cmd == "help":
            _out(HELP_TEXT)
        elif cmd == "clear":
            _out("\n" * 30 + "— consola limpia —")
        elif cmd == "stop":
            _out("Apagando SoulBot...")
            await bot.close()
            return
        elif cmd in COMMANDS:
            # args: para say/dm/embed/kick/ban el 2º param es el resto del texto
            if cmd in ("say", "dm", "embed"):
                sub = raw_args.split(maxsplit=1)
                call_args = sub if len(sub) == 2 else sub
            elif cmd == "nick":
                call_args = raw_args.split(maxsplit=2)
            elif cmd in ("kick", "ban", "timeout"):
                sub = raw_args.split(maxsplit=3)
                call_args = sub
            else:
                call_args = raw_args.split() if raw_args else []
            try:
                await COMMANDS[cmd](bot, call_args)
            except Exception as e:
                _err(e)
        else:
            _out(f"❓ '{cmd}' no existe. Escribe 'help'.")
