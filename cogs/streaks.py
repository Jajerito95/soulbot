from __future__ import annotations
import datetime
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from utils.levels_engine import award_xp
from config import COLOR

def today_str() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")

def yesterday_str() -> str:
    return (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

# rewards for /daily streak 1-7
DAILY_STREAK_REWARDS = {
    1: (50, 50, "🤍 Día 1"),
    2: (100, 80, "💚 Día 2"),
    3: (150, 120, "💙 Día 3"),
    4: (250, 180, "💜 Día 4"),
    5: (400, 250, "🧡 Día 5"),
    6: (600, 350, "❤️ Día 6"),
    7: (1000, 500, "💎 Día 7 ¡CAJA GRANDE!"),
}

async def update_activity_streak(guild_id: int, user_id: int):
    # general racha: cualquier actividad (mensaje, voz, mision) mantiene racha
    today = today_str()
    cur = await db.db().execute("SELECT current_streak, last_date FROM streaks WHERE guild_id=? AND user_id=? AND type='activity'", (guild_id, user_id))
    row = await cur.fetchone()
    if not row:
        await db.db().execute("INSERT INTO streaks (guild_id, user_id, type, current_streak, max_streak, last_date) VALUES (?, ?, 'activity', 1, 1, ?)", (guild_id, user_id, today))
        await db.db().commit()
        return 1
    streak, last = row
    if last == today:
        return streak
    if last == yesterday_str():
        streak += 1
    else:
        streak = 1
    await db.db().execute("UPDATE streaks SET current_streak=?, max_streak=MAX(max_streak, ?), last_date=? WHERE guild_id=? AND user_id=? AND type='activity'", (streak, streak, today, guild_id, user_id))
    await db.db().commit()
    return streak

async def update_daily_streak(guild_id: int, user_id: int) -> tuple[int, int, int, str]:
    # /daily streak 1-7 escalado
    today = today_str()
    cur = await db.db().execute("SELECT current_streak, last_date FROM streaks WHERE guild_id=? AND user_id=? AND type='daily'", (guild_id, user_id))
    row = await cur.fetchone()
    if not row:
        await db.db().execute("INSERT INTO streaks (guild_id, user_id, type, current_streak, max_streak, last_date) VALUES (?, ?, 'daily', 1, 1, ?)", (guild_id, user_id, today))
        await db.db().commit()
        coins, xp, label = DAILY_STREAK_REWARDS[1]
        return 1, coins, xp, label
    streak, last = row
    if last == today:
        # ya reclamó hoy
        coins, xp, label = DAILY_STREAK_REWARDS[streak]
        return streak, 0, 0, label
    if last == yesterday_str():
        streak = streak + 1 if streak < 7 else 1
    else:
        streak = 1
    await db.db().execute("UPDATE streaks SET current_streak=?, max_streak=MAX(max_streak, ?), last_date=? WHERE guild_id=? AND user_id=? AND type='daily'", (streak, streak, today, guild_id, user_id))
    await db.db().commit()
    coins, xp, label = DAILY_STREAK_REWARDS[streak]
    return streak, coins, xp, label

class StreaksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        if len(message.content) < 3: return
        await update_activity_streak(message.guild.id, message.author.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if member.bot or not member.guild: return
        # si entra a VC, cuenta como actividad
        if before.channel is None and after.channel is not None:
            await update_activity_streak(member.guild.id, member.id)

    streaks = app_commands.Group(name="racha", description="Rachas diarias")

    @streaks.command(name="ver", description="Mira tus rachas")
    @app_commands.describe(usuario="Usuario a consultar")
    async def ver(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        target = usuario or interaction.user
        cur = await db.db().execute("SELECT type, current_streak, max_streak, last_date FROM streaks WHERE guild_id=? AND user_id=?", (interaction.guild_id, target.id))
        rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message(embed=error_embed("Sin rachas aún. Habla, entra a VC o haz /daily."), ephemeral=True)
            return
        lines = []
        for typ, cur_s, max_s, last in rows:
            label = "🔥 Actividad (mensaje/misión/voz)" if typ=="activity" else "📅 Daily"
            lines.append(f"{label}: **{cur_s}** días (récord {max_s}) — último {last}")
            if typ=="daily":
                nxt = cur_s + 1 if cur_s < 7 else 1
                coins, xp, lbl = DAILY_STREAK_REWARDS[nxt]
                lines.append(f"  → Próximo {lbl}: +{coins} coins +{xp} XP")
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title=f"🔥 Rachas de {target.display_name}"), ephemeral=True)

    @streaks.command(name="top", description="Top rachas del server")
    async def top(self, interaction: discord.Interaction):
        cur = await db.db().execute("SELECT user_id, current_streak FROM streaks WHERE guild_id=? AND type='daily' ORDER BY current_streak DESC LIMIT 10", (interaction.guild_id,))
        rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message(embed=error_embed("Sin rachas aún."))
            return
        lines = [f"**{i+1}.** <@{uid}> — **{streak}** días" for i, (uid, streak) in enumerate(rows)]
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title="🏆 Top Rachas Daily"))

    @streaks.command(name="reset", description="Resetea racha y cooldown daily (Staff o propio)")
    @app_commands.describe(usuario="Usuario a resetear (Staff puede elegir otro, vacío = tú)")
    async def reset(self, interaction: discord.Interaction, usuario: Optional[discord.Member]=None):
        target = usuario or interaction.user
        # solo staff puede resetear a otro
        if target.id != interaction.user.id and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff puede resetear a otro."), ephemeral=True)
            return
        await db.db().execute("DELETE FROM streaks WHERE guild_id=? AND user_id=?", (interaction.guild_id, target.id))
        # resetea cooldown daily (economy.last_daily)
        await db.db().execute("UPDATE economy SET last_daily=NULL WHERE guild_id=? AND user_id=?", (interaction.guild_id, target.id))
        await db.db().commit()
        await interaction.response.send_message(embed=success_embed(f"Racha y cooldown de {target.mention} reseteados. Puede usar `/daily` de nuevo.", title="🔄 Reset"), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(StreaksCog(bot))
