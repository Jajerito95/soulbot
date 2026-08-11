from __future__ import annotations
import re
import discord

import database as db
from cogs.sanction_data import INFRACTIONS, get_punishment
from cogs.logs import log_embed
from config import COLOR_ERROR

IMGUR_RE = re.compile(r"^https?://(www\.)?(i\.)?imgur\.com/.+", re.IGNORECASE)


def is_imgur(url: str) -> bool:
    return bool(IMGUR_RE.match(url.strip()))


def requires_evidence(punishment: str) -> bool:
    """Evidencia obligatoria en sanciones 'grandes': permanentes o bans >= 7 días."""
    if punishment == "perm":
        return True
    if punishment.endswith("d"):
        return int(punishment[:-1]) >= 7
    return False


async def _send_log(guild: discord.Guild, title: str, description: str):
    config = await db.get_guild_config(guild.id)
    if config["logs_channel_id"] and config["logs_moderation"]:
        channel = guild.get_channel(config["logs_channel_id"])
        if channel:
            await channel.send(embed=log_embed(title, description, color=COLOR_ERROR))


async def apply_sanction(
    guild: discord.Guild,
    member: discord.Member,
    infraction_key: str,
    staff_id: int,
    reason: str,
    evidence_url: str | None = None,
) -> dict:
    """
    Aplica automáticamente la sanción correspondiente según el historial del usuario
    para esa infracción. Devuelve {punishment, sanction_id, count}.
    """
    label = INFRACTIONS[infraction_key]["label"]
    previous_count = await db.get_infraction_count(guild.id, member.id, infraction_key)
    punishment = get_punishment(infraction_key, previous_count)
    await db.increment_infraction_count(guild.id, member.id, infraction_key)

    full_reason = f"[{label}] {reason}"

    try:
        await member.send(
            embed=discord.Embed(
                title="🛡️ Sanción aplicada",
                description=f"Has recibido una sanción en **{guild.name}**.\n"
                f"⚙️ Infracción: {label}\n📝 Razón: {reason}\n⚖️ Sanción: {punishment_label(punishment)}",
                color=COLOR_ERROR,
            )
        )
    except discord.Forbidden:
        pass

    if punishment == "warn":
        action = "warn"
    elif punishment == "warn_change":
        action = "warn"
        if infraction_key == "nick_ofensivo":
            try:
                await member.edit(nick=None, reason="Nick ofensivo - reseteo automático")
            except discord.Forbidden:
                pass
    elif punishment == "perm":
        action = "ban"
        await guild.ban(member, reason=full_reason)
    else:
        days = int(punishment[:-1])
        action = "ban"
        await guild.ban(member, reason=full_reason)
        await db.add_temp_ban(guild.id, member.id, days)

    sanction_id = await db.log_staff_action(guild.id, member.id, staff_id, action, full_reason, evidence_url)

    desc = (
        f"👤 Usuario: {member.mention} (`{member.id}`)\n"
        f"⚙️ Infracción: {label}\n"
        f"⚖️ Sanción: {punishment_label(punishment)} (reincidencia #{previous_count + 1})\n"
        f"📝 Razón: {reason}\n🆔 ID: `#{sanction_id}`"
    )
    if evidence_url:
        desc += f"\n🔗 Evidencia: {evidence_url}"

    await _send_log(guild, "🛡️ Sanción automática aplicada", desc)

    return {"punishment": punishment, "sanction_id": sanction_id, "count": previous_count + 1}


def punishment_label(punishment: str) -> str:
    if punishment == "warn":
        return "⚠️ Warn"
    if punishment == "warn_change":
        return "⚠️ Warn + cambio obligatorio"
    if punishment == "perm":
        return "🔨 Ban permanente"
    return f"🔨 Ban temporal ({punishment})"
