from __future__ import annotations
import datetime
from zoneinfo import ZoneInfo

import discord
import database as db

TZ = ZoneInfo("Europe/Madrid")
WEEKEND_MULTIPLIER = 2.0  # jueves 23:00 -> domingo 23:00


def xp_for_level(level: int) -> int:
    """XP necesaria para pasar del nivel `level` al siguiente (curva estilo Mee6)."""
    return 5 * (level ** 2) + 50 * level + 100


def level_from_xp(xp: int) -> tuple[int, int, int]:
    """Devuelve (nivel_actual, xp_en_nivel_actual, xp_necesaria_para_subir)."""
    level = 0
    remaining = xp
    while remaining >= xp_for_level(level):
        remaining -= xp_for_level(level)
        level += 1
        if level > 1000:  # salvaguarda
            break
    return level, remaining, xp_for_level(level)


def is_weekend_bonus_now() -> bool:
    now = datetime.datetime.now(TZ)
    weekday = now.weekday()  # lunes=0 ... domingo=6
    # jueves (3) 23:00 -> domingo (6) 23:00
    if weekday == 3 and now.hour >= 23:
        return True
    if weekday in (4, 5):
        return True
    if weekday == 6 and now.hour < 23:
        return True
    return False


def _not_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return True
    return datetime.datetime.utcnow().isoformat() < expires_at


async def get_effective_multiplier(guild_id: int, user_id: int) -> float:
    config = await db.get_guild_config(guild_id)
    multiplier = 1.0

    if config["xp_global_multiplier"] and _not_expired(config["xp_global_multiplier_expires"]):
        multiplier *= config["xp_global_multiplier"]

    user_mult = await db.get_user_multiplier(guild_id, user_id)
    if user_mult and _not_expired(user_mult[1]):
        multiplier *= user_mult[0]

    if config["xp_weekend_enabled"] and is_weekend_bonus_now():
        multiplier *= WEEKEND_MULTIPLIER

    return multiplier


async def award_xp(guild: discord.Guild, member: discord.Member, base_amount: int, log: bool = True, apply_multiplier: bool = True, _boss_reward: bool = False) -> dict:
    """Aplica multiplicadores, suma XP, detecta subida de nivel y aplica recompensas de rol."""
    multiplier = await get_effective_multiplier(guild.id, member.id) if apply_multiplier else 1.0
    amount = round(base_amount * multiplier)

    data = await db.get_level_data(guild.id, member.id)
    new_xp = data["xp"] + amount
    new_level, _, _ = level_from_xp(new_xp)
    leveled_up = new_level > data["level"]

    await db.set_level_data(guild.id, member.id, new_xp, new_level)
    if log:
        await db.log_xp_event(guild.id, member.id, amount)

    new_roles = []
    coins_awarded = 0
    if leveled_up:
        config = await db.get_guild_config(guild.id)
        coins_awarded = new_level * config["levelup_coin_multiplier"]
        await db.add_coins(guild.id, member.id, coins_awarded)

        rewards = await db.get_level_rewards(guild.id)
        for level, role_id in rewards:
            if level <= new_level:
                role = guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason="Recompensa de nivel")
                        new_roles.append(role)
                    except discord.Forbidden:
                        pass

    return {
        "amount": amount, "new_xp": new_xp, "new_level": new_level,
        "leveled_up": leveled_up, "new_roles": new_roles, "coins_awarded": coins_awarded,
        "_boss_reward": _boss_reward,
    }


def progress_bar(current: int, total: int, length: int = 12) -> str:
    filled = int(length * current / total) if total else 0
    return "▰" * filled + "▱" * (length - filled)
