from __future__ import annotations
import asyncio
import datetime
import random
import json
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from utils.levels_engine import award_xp, progress_bar
from config import COLOR, COLOR_SUCCESS

# ---------- pool ----------
MISSION_POOL = [
    {"id":"msg_15", "type":"messages", "goal":15, "desc":"Envía **{goal}** mensajes", "coins":120, "xp":80},
    {"id":"msg_30", "type":"messages", "goal":30, "desc":"Envía **{goal}** mensajes", "coins":180, "xp":120},
    {"id":"msg_50", "type":"messages", "goal":50, "desc":"Envía **{goal}** mensajes", "coins":250, "xp":150},
    {"id":"voice_15", "type":"voice", "goal":15, "desc":"Permanece **{goal} min** en voz", "coins":150, "xp":100},
    {"id":"voice_30", "type":"voice", "goal":30, "desc":"Permanece **{goal} min** en voz", "coins":200, "xp":150},
    {"id":"voice_60", "type":"voice", "goal":60, "desc":"Permanece **{goal} min** en voz", "coins":300, "xp":200},
    {"id":"work_1", "type":"work", "goal":1, "desc":"Haz **/work** 1 vez", "coins":100, "xp":80},
    {"id":"work_2", "type":"work", "goal":2, "desc":"Haz **/work** 2 veces", "coins":200, "xp":150},
    {"id":"game_1", "type":"game_win", "goal":1, "desc":"Gana **1** minijuego (/tictactoe, /connect4)", "coins":150, "xp":100},
    {"id":"game_2", "type":"game_win", "goal":2, "desc":"Gana **2** minijuegos", "coins":250, "xp":180},
    {"id":"coins_500", "type":"coins", "goal":500, "desc":"Gana **500** SoulCoins", "coins":0, "xp":120},
    {"id":"xp_300", "type":"level_xp", "goal":300, "desc":"Gana **300 XP**", "coins":150, "xp":0},
    {"id":"invite_1", "type":"invite", "goal":1, "desc":"Invita a **1** persona", "coins":250, "xp":200},
]

def today_str() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")

def mystery_box() -> tuple[int,int,str]:
    """returns (coins,xp,rarity label)"""
    r = random.random()
    if r < 0.05:  # legendaria 5%
        return random.randint(400,600), random.randint(250,350), "💎 LEGENDARIA"
    if r < 0.20:  # epica 15%
        return random.randint(250,400), random.randint(150,250), "💜 ÉPICA"
    if r < 0.50:  # rara 30%
        return random.randint(150,250), random.randint(100,180), "💙 RARA"
    return random.randint(80,150), random.randint(60,120), "🤍 COMÚN"

async def ensure_daily_missions(guild_id: int, user_id: int):
    date = today_str()
    cur = await db.db().execute("SELECT COUNT(*) FROM user_missions WHERE guild_id=? AND user_id=? AND date=?", (guild_id, user_id, date))
    cnt = (await cur.fetchone())[0]
    if cnt >= 5:
        return
    # generate 5 random unique
    chosen = random.sample(MISSION_POOL, 5)
    for m in chosen:
        try:
            await db.db().execute(
                "INSERT OR IGNORE INTO user_missions (guild_id, user_id, date, mission_id, type, goal, progress, claimed, reward_coins, reward_xp, description) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (guild_id, user_id, date, m["id"], m["type"], m["goal"], 0, 0, m["coins"], m["xp"], m["desc"].format(goal=m["goal"]))
            )
        except: pass
    await db.db().commit()

async def get_missions(guild_id: int, user_id: int):
    date = today_str()
    await ensure_daily_missions(guild_id, user_id)
    cur = await db.db().execute("SELECT * FROM user_missions WHERE guild_id=? AND user_id=? AND date=? ORDER BY mission_id", (guild_id, user_id, date))
    rows = await cur.fetchall()
    cols = [d[0] for d in cur.description] if rows else []
    return [dict(zip(cols, r)) for r in rows]

async def add_progress(guild_id: int, user_id: int, typ: str, amount: int = 1):
    date = today_str()
    await ensure_daily_missions(guild_id, user_id)
    cur = await db.db().execute("SELECT * FROM user_missions WHERE guild_id=? AND user_id=? AND date=? AND type=? AND claimed=0", (guild_id, user_id, date, typ))
    rows = await cur.fetchall()
    if not rows:
        return
    cols = [d[0] for d in cur.description]
    for r in rows:
        m = dict(zip(cols, r))
        new_prog = min(int(m["progress"]) + amount, int(m["goal"]))
        if new_prog != m["progress"]:
            await db.db().execute("UPDATE user_missions SET progress=? WHERE guild_id=? AND user_id=? AND date=? AND mission_id=?", (new_prog, guild_id, user_id, date, m["mission_id"]))
    await db.db().commit()

# ---------- View ----------
class MissionsView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id

    async def _claim_one(self, interaction: discord.Interaction, mission_id: str):
        if interaction.user.id != self.user_id and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo tú puedes reclamar tus misiones."), ephemeral=True)
            return
        date = today_str()
        cur = await db.db().execute("SELECT * FROM user_missions WHERE guild_id=? AND user_id=? AND date=? AND mission_id=?", (self.guild_id, self.user_id, date, mission_id))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("Misión no encontrada."), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        m = dict(zip(cols, row))
        if int(m["claimed"]) == 1:
            await interaction.response.send_message(embed=error_embed("Ya reclamaste esta caja."), ephemeral=True)
            return
        if int(m["progress"]) < int(m["goal"]):
            await interaction.response.send_message(embed=error_embed(f"Aún no completada: {m['progress']}/{m['goal']}"), ephemeral=True)
            return
        # mystery box
        coins, xp, rarity = mystery_box()
        # base reward + box bonus
        total_coins = int(m["reward_coins"]) + coins
        total_xp = int(m["reward_xp"]) + xp
        await db.db().execute("UPDATE user_missions SET claimed=1 WHERE guild_id=? AND user_id=? AND date=? AND mission_id=?", (self.guild_id, self.user_id, date, mission_id))
        await db.db().commit()
        # award
        if total_coins > 0:
            await db.add_coins(self.guild_id, self.user_id, total_coins, reason=f"mission:{mission_id}")
        if total_xp > 0:
            guild = interaction.guild
            member = guild.get_member(self.user_id) or await guild.fetch_member(self.user_id)
            if member:
                result = await award_xp(guild, member, total_xp, log=True)
                # boss damage: XP × 5
                try:
                    boss_cog = interaction.client.get_cog("BossCog")
                    if boss_cog:
                        await boss_cog._handle_xp_damage(guild.id, self.user_id, result["amount"])
                except Exception:
                    pass
        # check bonus all 5 claimed?
        cur2 = await db.db().execute("SELECT COUNT(*) FROM user_missions WHERE guild_id=? AND user_id=? AND date=? AND claimed=1", (self.guild_id, self.user_id, date))
        claimed_cnt = (await cur2.fetchone())[0]
        bonus_msg = ""
        if claimed_cnt >= 5:
            # check if bonus already given today
            cur3 = await db.db().execute("SELECT value FROM guild_kv WHERE guild_id=? AND key=?", (self.guild_id, f"mission_bonus_{self.user_id}_{date}"))
            row3 = await cur3.fetchone()
            if not row3:
                b_coins, b_xp, b_rarity = 500, 300, "💎 BONUS 5/5"
                await db.add_coins(self.guild_id, self.user_id, b_coins, reason="mission_bonus_5")
                guild = interaction.guild
                member = guild.get_member(self.user_id) or await guild.fetch_member(self.user_id)
                if member:
                    result = await award_xp(guild, member, b_xp, log=True)
                    # boss damage: XP × 5
                    try:
                        boss_cog = interaction.client.get_cog("BossCog")
                        if boss_cog:
                            await boss_cog._handle_xp_damage(guild.id, self.user_id, result["amount"])
                    except Exception:
                        pass
                await db.db().execute("INSERT OR REPLACE INTO guild_kv (guild_id, key, value) VALUES (?,?,?)", (self.guild_id, f"mission_bonus_{self.user_id}_{date}", "1"))
                await db.db().commit()
                bonus_msg = f"\n\n🎉 ¡**BONUS 5/5**! Caja extra {b_rarity} +{b_coins} coins +{b_xp} XP"

        await interaction.response.send_message(embed=success_embed(f"📦 Caja {rarity} abierta!\n+**{total_coins}** SoulCoins +**{total_xp}** XP\n*Misión:* {m['description']}{bonus_msg}", title="📦 Recompensa"), ephemeral=True)
        # refresh with Pillow
        try:
            from utils.card_renderer import render_missions_card
            missions = await get_missions(self.guild_id, self.user_id)
            new_claimed = sum(1 for m in missions if int(m["claimed"]))
            member = interaction.guild.get_member(self.user_id)
            username = member.display_name if member else "User"
            avatar = member.display_avatar.url if member else ""
            buf = await render_missions_card(username, avatar, missions, new_claimed, today_str())
            file = discord.File(buf, filename="missions.png")
            embed = base_embed(f"📋 Misiones — {today_str()}\n{new_claimed}/5 reclamadas", COLOR, title="📋 Misiones diarias")
            embed.set_image(url="attachment://missions.png")
            embed.set_footer(text="Reset 00:00 UTC • SoulSeeker™")
            done = sum(1 for m in missions if int(m["progress"]) >= int(m["goal"]))
            if done == 5 and new_claimed < 5:
                embed.description += "\n\n💎 ¡Completa las 5 y reclama el **BONUS épico**!"
            await interaction.message.edit(embed=embed, attachments=[file], view=self)
        except Exception:
            try:
                embed = await build_missions_embed(self.guild_id, self.user_id)
                await interaction.message.edit(embed=embed, view=self)
            except: pass

    def _btn(self, mission: dict):
        done = int(mission["progress"]) >= int(mission["goal"])
        claimed = int(mission["claimed"]) == 1
        label = f"{mission['mission_id']} ({mission['progress']}/{mission['goal']})"
        if claimed:
            label = f"✅ {mission['mission_id']}"
            style = discord.ButtonStyle.secondary
            disabled = True
        elif done:
            label = f"📦 {mission['mission_id']}"
            style = discord.ButtonStyle.success
            disabled = False
        else:
            style = discord.ButtonStyle.primary
            disabled = False
        btn = discord.ui.Button(label=label[:80], style=style, disabled=disabled, custom_id=f"mission:{mission['mission_id']}")
        async def cb(interaction: discord.Interaction):
            await self._claim_one(interaction, mission["mission_id"])
        btn.callback = cb
        return btn

def build_missions_view(guild_id: int, user_id: int, missions: list[dict]) -> MissionsView:
    view = MissionsView(guild_id, user_id)
    for m in missions[:5]:
        view.add_item(view._btn(m))
    return view

async def build_missions_embed(guild_id: int, user_id: int) -> discord.Embed:
    missions = await get_missions(guild_id, user_id)
    date = today_str()
    lines = []
    for m in missions:
        prog = int(m["progress"])
        goal = int(m["goal"])
        bar = progress_bar(prog, goal, 10)
        status = "✅ Reclamada" if int(m["claimed"]) else ("📦 Lista para reclamar" if prog >= goal else "⏳ En progreso")
        lines.append(f"**{m['description']}**\n{bar} `{prog}/{goal}` — {status}\n*Recompensa base:* {m['reward_coins']} coins + {m['reward_xp']} XP + caja sorpresa")
    claimed = sum(1 for m in missions if int(m["claimed"]))
    done = sum(1 for m in missions if int(m["progress"]) >= int(m["goal"]))
    embed = base_embed("\n\n".join(lines) or "Sin misiones hoy.", COLOR, title=f"📋 Misiones diarias — {date} — {done}/5 completadas, {claimed}/5 reclamadas")
    embed.set_footer(text="Reset 00:00 UTC • SoulSeeker™")
    if done == 5 and claimed < 5:
        embed.description += "\n\n🎉 ¡Completa las 5 y reclama el **BONUS épico**!"
    return embed

# ---------- Cog ----------
class MissionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_loop.start()
        self.reset_loop.start()

    def cog_unload(self):
        try: self.voice_loop.cancel()
        except: pass
        try: self.reset_loop.cancel()
        except: pass

    @tasks.loop(minutes=1)
    async def voice_loop(self):
        try:
            await self.bot.wait_until_ready()
            for guild in self.bot.guilds:
                for vc in guild.voice_channels:
                    for member in vc.members:
                        if member.bot: continue
                        await add_progress(guild.id, member.id, "voice", 1)
        except: pass

    @tasks.loop(minutes=60)
    async def reset_loop(self):
        # prune old missions >7d
        try:
            cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
            await db.db().execute("DELETE FROM user_missions WHERE date < ?", (cutoff,))
            await db.db().execute("DELETE FROM guild_kv WHERE key LIKE 'mission_bonus_%' AND key < ?", (f"mission_bonus_{cutoff}",))
            await db.db().commit()
        except: pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        if len(message.content) < 2: return
        await add_progress(message.guild.id, message.author.id, "messages", 1)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # invite progress handled via invites cog? we check inviter
        try:
            # try to find inviter via invites table? simplified: give to all online staff? skip
            pass
        except: pass

    # hook for economy / work / game win via manual calls from other cogs
    # we expose a global function that other cogs can import
    # but also we poll via events: we listen for custom dispatch
    @commands.Cog.listener()
    async def on_mission_progress(self, guild_id: int, user_id: int, typ: str, amount: int = 1):
        await add_progress(guild_id, user_id, typ, amount)

    missions = app_commands.Group(name="misiones", description="Misiones diarias 5/5 + cajas sorpresa")

    @missions.command(name="ver", description="Ve tus 5 misiones diarias + progreso")
    @app_commands.describe(usuario="Ver misiones de otro usuario (opcional)")
    async def ver(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        target = usuario or interaction.user
        missions = await get_missions(interaction.guild_id, target.id)
        view = build_missions_view(interaction.guild_id, target.id, missions)
        # if viewing other, disable claim
        if target.id != interaction.user.id:
            for child in view.children:
                child.disabled = True
        # Pillow card
        try:
            await interaction.response.defer(ephemeral=(target.id == interaction.user.id))
            from utils.card_renderer import render_missions_card
            claimed = sum(1 for m in missions if int(m["claimed"]))
            date_label = today_str()
            buf = await render_missions_card(target.display_name, target.display_avatar.url, missions, claimed, date_label)
            file = discord.File(buf, filename="missions.png")
            embed = base_embed(f"📋 Misiones de **{target.display_name}** — {today_str()}\n{claimed}/5 reclamadas", COLOR, title="📋 Misiones diarias")
            embed.set_image(url="attachment://missions.png")
            embed.set_footer(text="Reset 00:00 UTC • SoulSeeker™")
            done = sum(1 for m in missions if int(m["progress"]) >= int(m["goal"]))
            if done == 5 and claimed < 5:
                embed.description += "\n\n💎 ¡Completa las 5 y reclama el **BONUS épico**!"
            await interaction.followup.send(embed=embed, file=file, view=view)
        except Exception:
            embed = await build_missions_embed(interaction.guild_id, target.id)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=(target.id == interaction.user.id))

    @missions.command(name="reroll", description="Rerolea tus misiones de hoy (Staff o 1/día)")
    async def reroll(self, interaction: discord.Interaction):
        # allow 1 free reroll per day, staff unlimited
        is_staff = interaction.user.guild_permissions.manage_guild
        date = today_str()
        cur = await db.db().execute("SELECT value FROM guild_kv WHERE guild_id=? AND key=?", (interaction.guild_id, f"reroll_{interaction.user.id}_{date}"))
        row = await cur.fetchone()
        if row and not is_staff:
            await interaction.response.send_message(embed=error_embed("Ya hiciste reroll hoy. Solo Staff puede repetir."), ephemeral=True)
            return
        await db.db().execute("DELETE FROM user_missions WHERE guild_id=? AND user_id=? AND date=?", (interaction.guild_id, interaction.user.id, date))
        await db.db().commit()
        if not is_staff:
            await db.db().execute("INSERT OR REPLACE INTO guild_kv (guild_id, key, value) VALUES (?,?,?)", (interaction.guild_id, f"reroll_{interaction.user.id}_{date}", "1"))
            await db.db().commit()
        await ensure_daily_missions(interaction.guild_id, interaction.user.id)
        embed = await build_missions_embed(interaction.guild_id, interaction.user.id)
        missions = await get_missions(interaction.guild_id, interaction.user.id)
        view = build_missions_view(interaction.guild_id, interaction.user.id, missions)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MissionsCog(bot))

# helper for other cogs to dispatch progress without import cycle
def dispatch_mission(bot: commands.Bot, guild_id: int, user_id: int, typ: str, amount: int = 1):
    try:
        bot.dispatch("mission_progress", guild_id, user_id, typ, amount)
    except: pass
