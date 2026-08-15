"""
Sistema de emojis custom de SoulBot.

En vez de hardcodear IDs (que solo sirven en UN servidor), busca el emoji
por NOMBRE entre los emojis del servidor en el momento de usarlo. Si no lo
encuentra (porque el Staff aún no lo ha subido), usa un emoji Unicode de
respaldo — así nada se rompe mientras se van subiendo los custom poco a poco.
"""
from __future__ import annotations
import discord

# nombre_interno -> emoji Unicode de respaldo
FALLBACKS: dict[str, str] = {
    # núcleo
    "success": "✅", "error": "❌", "warning": "⚠️", "loading": "⏳",
    "arrow": "➡️", "bullet": "•",
    # bienvenida / invitaciones
    "wave": "👋", "invite": "📨", "members": "👥",
    # tickets
    "ticket": "🎫", "claim": "🙋", "close": "🔒", "queue": "⏳", "adduser": "➕",
    # sugerencias / apelaciones
    "suggestion": "💡", "yes": "🟢", "no": "🔴", "appeal": "📮",
    # niveles
    "star": "⭐", "levelup": "🎉", "trophy": "🏆",
    "medal1": "🥇", "medal2": "🥈", "medal3": "🥉", "progress": "📈",
    # economía
    "coin": "💰", "shop": "🛒", "gift": "🎁", "key": "🔑", "boost": "⚡",
    # minijuegos
    "dice": "🎲", "game": "🎮", "brain": "🧠", "win": "🏆", "draw": "🤝",
    # moderación
    "shield": "🛡️", "ban": "🔨", "warn": "⚠️", "gavel": "⚖️",
    "automod": "🤖", "roletemp": "⏱️",
    # staff
    "settings": "⚙️", "logs": "📜", "backup": "💾", "maintenance": "🔧",
}

_cache: dict[tuple[int, str], str] = {}


def emoji(guild: discord.Guild | None, name: str) -> str:
    """Devuelve el emoji custom del servidor si existe (por nombre), si no el Unicode de respaldo."""
    fallback = FALLBACKS.get(name, "•")
    if guild is None:
        return fallback

    cache_key = (guild.id, name)
    if cache_key in _cache:
        return _cache[cache_key]

    found = discord.utils.get(guild.emojis, name=name)
    result = str(found) if found else fallback
    _cache[cache_key] = result
    return result


def clear_cache(guild_id: int | None = None):
    """Llamar tras subir/borrar/renombrar emojis para que se vuelvan a buscar."""
    global _cache
    if guild_id is None:
        _cache = {}
    else:
        _cache = {k: v for k, v in _cache.items() if k[0] != guild_id}
