from __future__ import annotations
import asyncio
import datetime
import json
import re
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR, COLOR_SUCCESS, COLOR_ERROR

# ---------- helpers ----------

DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.I)
UNIT_S = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

def parse_duration(s: str) -> Optional[int]:
    """'1h 30m' / '2d' / '1w' -> seconds. Returns None if invalid or <=0."""
    if not s:
        return None
    total = 0
    for num, unit in DURATION_RE.findall(s.lower()):
        try:
            total += int(num) * UNIT_S[unit.lower()]
        except: pass
    if total <= 0:
        # try plain number as minutes?
        try:
            v = int(s.strip())
            if v > 0:
                return v * 60
        except: pass
        return None
    if total > 60*60*24*30:  # max 30d
        total = 60*60*24*30
    return total

def human_duration(seconds: int) -> str:
    if seconds >= 604800:
        return f"{seconds//604800}w { (seconds%604800)//86400 }d".strip()
    if seconds >= 86400:
        return f"{seconds//86400}d { (seconds%86400)//3600 }h".strip()
    if seconds >= 3600:
        return f"{seconds//3600}h {(seconds%3600)//60}m".strip()
    if seconds >= 60:
        return f"{seconds//60}m"
    return f"{seconds}s"

def format_ts(ts: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(ts)
        return f"<t:{int(dt.timestamp())}:R> (<t:{int(dt.timestamp())}:F>)"
    except:
        return ts

async def _get_reqs(giveaway: dict) -> dict:
    try:
        return json.loads(giveaway.get("requirements") or "{}")
    except: return {}

async def _check_requirements(member: discord.Member, guild: discord.Guild, reqs: dict) -> tuple[bool, str]:
    # min_level
    if reqs.get("min_level"):
        try:
            data = await db.get_level_data(guild.id, member.id)
            if int(data.get("level", 0)) < int(reqs["min_level"]):
                return False, f"Necesitas nivel **{reqs['min_level']}** (tienes {data.get('level',0)}). Usa /rank."
        except: pass
    # min_invites
    if reqs.get("min_invites"):
        try:
            cur = await db.db().execute("SELECT invited_count FROM invites WHERE guild_id=? AND user_id=?", (guild.id, member.id))
            row = await cur.fetchone()
            cnt = row[0] if row else 0
            if cnt < int(reqs["min_invites"]):
                return False, f"Necesitas **{reqs['min_invites']}** invites (tienes {cnt})."
        except: pass
    # required_role
    if reqs.get("required_role"):
        try:
            rid = int(reqs["required_role"])
            if not any(r.id == rid for r in member.roles):
                role = guild.get_role(rid)
                name = role.mention if role else f"<@&{rid}>"
                return False, f"Necesitas el rol {name}."
        except: pass
    # min_account_days
    if reqs.get("min_account_days"):
        try:
            days = (datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
            if days < int(reqs["min_account_days"]):
                return False, f"Tu cuenta debe tener al menos **{reqs['min_account_days']}** días (tienes {days})."
        except: pass
    return True, ""

def build_giveaway_embed(giveaway: dict, participants: int) -> discord.Embed:
    ends = format_ts(giveaway["ends_at"])
    winners = giveaway["winners_count"]
    prize = giveaway["prize"]
    desc = giveaway.get("description") or ""
    host = f"<@{giveaway['host_id']}>"
    reqs = {}
    try: reqs = json.loads(giveaway.get("requirements") or "{}")
    except: pass
    req_lines = []
    if reqs.get("min_level"): req_lines.append(f"⭐ Nivel ≥ {reqs['min_level']}")
    if reqs.get("min_invites"): req_lines.append(f"📨 Invites ≥ {reqs['min_invites']}")
    if reqs.get("required_role"): req_lines.append(f"🎭 Rol <@&{reqs['required_role']}>")
    if reqs.get("min_account_days"): req_lines.append(f"📅 Cuenta ≥ {reqs['min_account_days']}d")
    req_text = " • ".join(req_lines) if req_lines else "Sin requisitos"
    embed = base_embed(
        f"🎁 **Premio:** {prize}\n"
        f"{desc + chr(10) if desc else ''}"
        f"👑 Host: {host}\n"
        f"⏰ Finaliza: {ends}\n"
        f"🏆 Ganadores: **{winners}**\n"
        f"👥 Participantes: **{participants}**\n"
        f"📋 Requisitos: {req_text}\n\n"
        f"Pulsa **🎉 Participar** para entrar.",
        COLOR, title="🎉 SORTEO"
    )
    embed.set_footer(text=f"ID {giveaway['id']} • SoulSeeker™")
    return embed

# ---------- View ----------

class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id: int):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.participar.custom_id = f"soulbot:giveaway:{giveaway_id}"

    @discord.ui.button(label="🎉 Participar (0)", style=discord.ButtonStyle.success, custom_id="soulbot:giveaway:0")
    async def participar(self, interaction: discord.Interaction, button: discord.ui.Button):
        # custom_id carries giveaway_id
        try:
            gid = int(interaction.data["custom_id"].split(":")[-1])
        except:
            gid = self.giveaway_id
        # fetch giveaway
        cur = await db.db().execute("SELECT * FROM giveaways WHERE id=?", (gid,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("Sorteo no encontrado o ya finalizado."), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        gw = dict(zip(cols, row))
        if gw["status"] != "active":
            await interaction.response.send_message(embed=error_embed("Este sorteo ya no está activo."), ephemeral=True)
            return
        # check ends_at
        try:
            ends = datetime.datetime.fromisoformat(gw["ends_at"])
            if datetime.datetime.utcnow() >= ends:
                await interaction.response.send_message(embed=error_embed("Este sorteo ya finalizó."), ephemeral=True)
                return
        except: pass
        # check already entered
        cur2 = await db.db().execute("SELECT 1 FROM giveaway_entries WHERE giveaway_id=? AND user_id=?", (gid, interaction.user.id))
        if await cur2.fetchone():
            await interaction.response.send_message(embed=error_embed("Ya estás participando. ¡Suerte!"), ephemeral=True)
            return
        # check requirements
        reqs = await _get_reqs(gw)
        ok, msg = await _check_requirements(interaction.user, interaction.guild, reqs)  # type: ignore
        if not ok:
            await interaction.response.send_message(embed=error_embed(msg), ephemeral=True)
            return
        # insert
        try:
            await db.db().execute("INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)", (gid, interaction.user.id))
            await db.db().commit()
        except Exception as e:
            if "UNIQUE" in str(e) or "PRIMARY" in str(e):
                await interaction.response.send_message(embed=error_embed("Ya estás participando."), ephemeral=True)
                return
            raise
        # update button count
        cur3 = await db.db().execute("SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id=?", (gid,))
        cnt = (await cur3.fetchone())[0]
        button.label = f"🎉 Participar ({cnt})"
        try:
            await interaction.response.edit_message(view=self)
        except:
            await interaction.response.send_message(embed=success_embed(f"¡Entraste al sorteo! Participantes: **{cnt}**"), ephemeral=True)
            return
        await interaction.followup.send(embed=success_embed(f"¡Participación registrada! 🎉\nParticipantes: **{cnt}**"), ephemeral=True)
        # also update embed count if possible
        try:
            if interaction.message and interaction.message.embeds:
                new_embed = build_giveaway_embed(gw, cnt)
                await interaction.message.edit(embed=new_embed, view=self)
        except: pass

# Modal for panel quick create
class GiveawayCreateModal(discord.ui.Modal, title="Crear Sorteo — Full custom"):
    prize = discord.ui.TextInput(label="Premio", placeholder="Ej: 1x Rango VIP + 5k SoulCoins", max_length=100)
    duration = discord.ui.TextInput(label="Duración (ej: 1h, 30m, 2d, 1w)", placeholder="1h", max_length=20)
    winners = discord.ui.TextInput(label="Nº ganadores (1-10)", placeholder="1", max_length=2)
    description = discord.ui.TextInput(label="Descripción / mensaje custom", placeholder="¡Participa y gana!", style=discord.TextStyle.paragraph, required=False, max_length=300)
    requirements = discord.ui.TextInput(label="Requisitos: nivel,invites,rolID,dias", placeholder="Ej: 5,2,123456789,7 (vacío = ninguno)", required=False, max_length=100)

    def __init__(self, cog: "GiveawaysCog", channel: discord.TextChannel):
        super().__init__()
        self.cog = cog
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        prize = str(self.prize.value).strip()
        dur_s = str(self.duration.value).strip()
        try: winners_n = max(1, min(10, int(str(self.winners.value).strip())))
        except: winners_n = 1
        desc = str(self.description.value).strip() if self.description.value else ""
        req_raw = str(self.requirements.value).strip() if self.requirements.value else ""
        secs = parse_duration(dur_s)
        if not secs:
            await interaction.followup.send(embed=error_embed("Duración inválida. Usa `10m`, `1h`, `2d`, `1w`."), ephemeral=True)
            return
        reqs = {}
        if req_raw:
            parts = [p.strip() for p in req_raw.split(",")]
            try:
                if len(parts) >= 1 and parts[0]: reqs["min_level"] = int(parts[0])
                if len(parts) >= 2 and parts[1]: reqs["min_invites"] = int(parts[1])
                if len(parts) >= 3 and parts[2]: reqs["required_role"] = int(parts[2])
                if len(parts) >= 4 and parts[3]: reqs["min_account_days"] = int(parts[3])
            except: pass
        await self.cog._create_giveaway(interaction, prize, secs, winners_n, self.channel, desc, reqs)

class GiveawayPanelView(discord.ui.View):
    def __init__(self, cog: "GiveawaysCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🎉 Crear Sorteo", style=discord.ButtonStyle.success, custom_id="soulbot:giveaway_panel_create")
    async def create_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff puede crear sorteos."), ephemeral=True)
            return
        modal = GiveawayCreateModal(self.cog, interaction.channel)  # type: ignore
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📋 Ver activos", style=discord.ButtonStyle.secondary, custom_id="soulbot:giveaway_panel_list")
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cur = await db.db().execute("SELECT * FROM giveaways WHERE guild_id=? AND status='active' ORDER BY ends_at", (interaction.guild_id,))
        rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message(embed=error_embed("No hay sorteos activos."), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        lines = []
        for r in rows[:10]:
            gw = dict(zip(cols, r))
            cur2 = await db.db().execute("SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id=?", (gw["id"],))
            cnt = (await cur2.fetchone())[0]
            lines.append(f"`#{gw['id']}` **{gw['prize']}** — {cnt} entraron — finaliza {format_ts(gw['ends_at'])} — <#{gw['channel_id']}>")
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title="📋 Sorteos activos"), ephemeral=True)

# ---------- Cog ----------

class GiveawaysCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_loop.start()

    def cog_unload(self):
        try: self.check_loop.cancel()
        except: pass

    @tasks.loop(seconds=30)
    async def check_loop(self):
        try:
            await self.bot.wait_until_ready()
            now = datetime.datetime.utcnow().isoformat()
            cur = await db.db().execute("SELECT * FROM giveaways WHERE status='active' AND ends_at <= ?", (now,))
            rows = await cur.fetchall()
            if not rows:
                return
            cols = [d[0] for d in cur.description]
            for r in rows[:5]:
                gw = dict(zip(cols, r))
                await self._end_giveaway(gw)
                await asyncio.sleep(1)
        except Exception as e:
            # log but don't crash loop
            try: print(f"[giveaways] check_loop error: {e}")
            except: pass

    @check_loop.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        # re-register persistent views
        try:
            self.bot.add_view(GiveawayPanelView(self))
        except: pass
        # re-register giveaway views for active giveaways
        try:
            cur = await db.db().execute("SELECT id FROM giveaways WHERE status='active'")
            rows = await cur.fetchall()
            for (gid,) in rows:
                try: self.bot.add_view(GiveawayView(gid))
                except: pass
        except: pass

    async def _create_giveaway(self, interaction: discord.Interaction, prize: str, duration_secs: int, winners: int, channel: discord.TextChannel, description: str, reqs: dict):
        guild = interaction.guild
        ends_at = (datetime.datetime.utcnow() + datetime.timedelta(seconds=duration_secs)).isoformat()
        req_json = json.dumps(reqs) if reqs else "{}"
        cur = await db.db().execute(
            "INSERT INTO giveaways (guild_id, channel_id, host_id, prize, description, winners_count, ends_at, status, requirements) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
            (guild.id, channel.id, interaction.user.id, prize, description, winners, ends_at, req_json)
        )
        await db.db().commit()
        gid = cur.lastrowid
        gw = {"id": gid, "guild_id": guild.id, "channel_id": channel.id, "host_id": interaction.user.id, "prize": prize, "description": description, "winners_count": winners, "ends_at": ends_at, "status": "active", "requirements": req_json}
        embed = build_giveaway_embed(gw, 0)
        view = GiveawayView(gid)
        try:
            self.bot.add_view(view)
        except: pass
        try:
            msg = await channel.send(embed=embed, view=view)
            await db.db().execute("UPDATE giveaways SET message_id=? WHERE id=?", (msg.id, gid))
            await db.db().commit()
        except discord.Forbidden:
            await interaction.followup.send(embed=error_embed(f"No tengo permisos para enviar en {channel.mention}."), ephemeral=True)
            await db.db().execute("DELETE FROM giveaways WHERE id=?", (gid,))
            await db.db().commit()
            return
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Error al enviar sorteo: `{e}`"), ephemeral=True)
            return
        await interaction.followup.send(embed=success_embed(f"✅ Sorteo `#{gid}` creado en {channel.mention}\n⏰ Finaliza {format_ts(ends_at)} — **{winners}** ganador(es)\n🎁 Premio: **{prize}**"), ephemeral=True)

    async def _end_giveaway(self, gw: dict):
        gid = gw["id"]
        guild = self.bot.get_guild(gw["guild_id"])
        if not guild:
            await db.db().execute("UPDATE giveaways SET status='ended' WHERE id=?", (gid,))
            await db.db().commit()
            return
        channel = guild.get_channel(gw["channel_id"])
        cur = await db.db().execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (gid,))
        entries = [r[0] for r in await cur.fetchall()]
        winners_n = int(gw["winners_count"])
        chosen = []
        if entries:
            # filter still in guild? optional
            chosen = random.sample(entries, min(winners_n, len(entries)))
        # update DB
        await db.db().execute("UPDATE giveaways SET status='ended' WHERE id=?", (gid,))
        await db.db().commit()
        # build result embed
        prize = gw["prize"]
        if chosen:
            mentions = ", ".join(f"<@{uid}>" for uid in chosen)
            desc = f"🎉 ¡Sorteo finalizado!\n🎁 **Premio:** {prize}\n🏆 **Ganador(es):** {mentions}\n\nFelicidades — contactad con el host <@{gw['host_id']}>."
        else:
            desc = f"🎉 Sorteo finalizado.\n🎁 **Premio:** {prize}\n😢 Nadie participó — sin ganadores."
        embed = base_embed(desc, COLOR_SUCCESS, title=f"🎉 Sorteo #{gid} — Finalizado")
        # try to edit original message
        if channel and gw.get("message_id"):
            try:
                msg = await channel.fetch_message(gw["message_id"])
                # disable view
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label=f"Finalizado — {len(entries)} participaron", style=discord.ButtonStyle.secondary, disabled=True))
                await msg.edit(embed=build_giveaway_embed(gw, len(entries)), view=view)
            except: pass
        if channel:
            try:
                await channel.send(embed=embed, content=" ".join(f"<@{uid}>" for uid in chosen) if chosen else None)
            except: pass
        # DM winners?
        for uid in chosen:
            try:
                member = guild.get_member(uid) or await guild.fetch_member(uid)
                if member:
                    try: await member.send(embed=base_embed(f"¡Felicidades! Has ganado **{prize}** en **{guild.name}** 🎉\nReclama tu premio contactando al staff.", COLOR_SUCCESS, title="🏆 ¡Has ganado un sorteo!"))
                    except: pass
            except: pass

    # ---------- Slash commands ----------

    giveaway = app_commands.Group(name="giveaway", description="Sorteos / Giveaways (Staff)", default_permissions=discord.Permissions(manage_guild=True))

    @giveaway.command(name="create", description="Crea un sorteo full custom (Staff)")
    @app_commands.describe(
        premio="Premio a sortear",
        duracion="Duración: ej 10m, 1h, 2d, 1w (full custom)",
        ganadores="Nº de ganadores 1-10",
        canal="Canal donde se publica (por defecto aquí)",
        descripcion="Mensaje/descripción custom (opcional)",
        min_nivel="Nivel mínimo requerido (opcional)",
        min_invites="Invites mínimos (opcional)",
        rol_requerido="Rol requerido para participar (opcional)",
        min_dias_cuenta="Días mínimos de antigüedad de cuenta (opcional)"
    )
    async def create(self, interaction: discord.Interaction, premio: str, duracion: str, ganadores: app_commands.Range[int, 1, 10] = 1, canal: Optional[discord.TextChannel] = None, descripcion: Optional[str] = None, min_nivel: Optional[int] = None, min_invites: Optional[int] = None, rol_requerido: Optional[discord.Role] = None, min_dias_cuenta: Optional[int] = None):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff puede crear sorteos."), ephemeral=True)
            return
        secs = parse_duration(duracion)
        if not secs:
            await interaction.response.send_message(embed=error_embed("Duración inválida. Usa `10m`, `1h`, `2d`, `1w` (max 30d). Ej: `1h 30m`."), ephemeral=True)
            return
        if len(premio) > 100:
            await interaction.response.send_message(embed=error_embed("Premio demasiado largo (max 100)."), ephemeral=True)
            return
        channel = canal or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(embed=error_embed("Canal debe ser de texto."), ephemeral=True)
            return
        reqs = {}
        if min_nivel is not None: reqs["min_level"] = int(min_nivel)
        if min_invites is not None: reqs["min_invites"] = int(min_invites)
        if rol_requerido is not None: reqs["required_role"] = rol_requerido.id
        if min_dias_cuenta is not None: reqs["min_account_days"] = int(min_dias_cuenta)
        await interaction.response.defer(ephemeral=True)
        await self._create_giveaway(interaction, premio.strip(), secs, int(ganadores), channel, (descripcion or "").strip(), reqs)

    @giveaway.command(name="panel", description="Envía panel con botón Crear Sorteo (Staff)")
    @app_commands.describe(canal="Canal donde enviar el panel (opcional)")
    async def panel(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        channel = canal or interaction.channel
        embed = base_embed(
            "Pulsa **🎉 Crear Sorteo** para abrir el modal full custom.\n"
            "• Premio, duración (`10m`/`1h`/`2d`), ganadores 1-10, descripción\n"
            "• Requisitos opcionales: `nivel,invites,rolID,dias` (ej `5,2,,7`)\n"
            "También puedes usar `/giveaway create` con todos los parámetros.",
            COLOR, title="🎉 Panel de Sorteos — SoulSeeker™"
        )
        view = GiveawayPanelView(self)
        try:
            self.bot.add_view(view)
        except: pass
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(embed=success_embed(f"Panel enviado en {channel.mention}."), ephemeral=True)

    @giveaway.command(name="list", description="Lista sorteos activos")
    async def list_cmd(self, interaction: discord.Interaction):
        cur = await db.db().execute("SELECT * FROM giveaways WHERE guild_id=? AND status='active' ORDER BY ends_at", (interaction.guild_id,))
        rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message(embed=error_embed("No hay sorteos activos."), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        lines = []
        for r in rows[:10]:
            gw = dict(zip(cols, r))
            cur2 = await db.db().execute("SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id=?", (gw["id"],))
            cnt = (await cur2.fetchone())[0]
            lines.append(f"`#{gw['id']}` **{gw['prize']}** — {cnt} entraron — finaliza {format_ts(gw['ends_at'])} — <#{gw['channel_id']}> — {gw['winners_count']} ganador(es)")
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title="📋 Sorteos activos"), ephemeral=True)

    @giveaway.command(name="entries", description="Muestra participantes de un sorteo")
    @app_commands.describe(id="ID del sorteo")
    async def entries(self, interaction: discord.Interaction, id: int):
        cur = await db.db().execute("SELECT * FROM giveaways WHERE id=? AND guild_id=?", (id, interaction.guild_id))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("Sorteo no encontrado."), ephemeral=True)
            return
        cur2 = await db.db().execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id=? LIMIT 50", (id,))
        uids = [r[0] for r in await cur2.fetchall()]
        if not uids:
            await interaction.response.send_message(embed=error_embed("Sin participantes aún."), ephemeral=True)
            return
        mentions = ", ".join(f"<@{uid}>" for uid in uids)
        await interaction.response.send_message(embed=base_embed(mentions, COLOR, title=f"👥 Participantes sorteo #{id} ({len(uids)})"), ephemeral=True)

    @giveaway.command(name="end", description="Finaliza un sorteo ahora (Staff)")
    @app_commands.describe(id="ID del sorteo")
    async def end(self, interaction: discord.Interaction, id: int):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        cur = await db.db().execute("SELECT * FROM giveaways WHERE id=? AND guild_id=?", (id, interaction.guild_id))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("Sorteo no encontrado."), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        gw = dict(zip(cols, row))
        if gw["status"] != "active":
            await interaction.response.send_message(embed=error_embed("Este sorteo ya no está activo."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._end_giveaway(gw)
        await interaction.followup.send(embed=success_embed(f"Sorteo `#{id}` finalizado a mano."), ephemeral=True)

    @giveaway.command(name="reroll", description="Sortea de nuevo ganadores (Staff)")
    @app_commands.describe(id="ID del sorteo finalizado", ganadores="Nº ganadores a sortear de nuevo")
    async def reroll(self, interaction: discord.Interaction, id: int, ganadores: app_commands.Range[int, 1, 10] = 1):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        cur = await db.db().execute("SELECT * FROM giveaways WHERE id=? AND guild_id=?", (id, interaction.guild_id))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("Sorteo no encontrado."), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        gw = dict(zip(cols, row))
        cur2 = await db.db().execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (id,))
        entries = [r[0] for r in await cur2.fetchall()]
        if not entries:
            await interaction.response.send_message(embed=error_embed("Sin participantes para reroll."), ephemeral=True)
            return
        chosen = random.sample(entries, min(int(ganadores), len(entries)))
        mentions = ", ".join(f"<@{uid}>" for uid in chosen)
        embed = base_embed(f"🔄 **Reroll sorteo #{id}**\n🎁 Premio: **{gw['prize']}**\n🏆 Nuevos ganador(es): {mentions}", COLOR_SUCCESS, title="🔄 Reroll")
        await interaction.response.send_message(embed=embed, content=mentions)

    @giveaway.command(name="cancel", description="Cancela un sorteo activo (Staff)")
    @app_commands.describe(id="ID del sorteo")
    async def cancel(self, interaction: discord.Interaction, id: int):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        cur = await db.db().execute("SELECT * FROM giveaways WHERE id=? AND guild_id=? AND status='active'", (id, interaction.guild_id))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("Sorteo activo no encontrado."), ephemeral=True)
            return
        await db.db().execute("UPDATE giveaways SET status='cancelled' WHERE id=?", (id,))
        await db.db().commit()
        await interaction.response.send_message(embed=success_embed(f"Sorteo `#{id}` cancelado."), ephemeral=True)
        # try to update message
        cols = [d[0] for d in cur.description]
        gw = dict(zip(cols, row))
        if gw.get("message_id"):
            guild = interaction.guild
            ch = guild.get_channel(gw["channel_id"])
            if ch:
                try:
                    msg = await ch.fetch_message(gw["message_id"])
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(label="Cancelado", style=discord.ButtonStyle.danger, disabled=True))
                    await msg.edit(view=view)
                except: pass

async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawaysCog(bot))
