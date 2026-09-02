from __future__ import annotations
import asyncio
import datetime
import random
import io
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

# ---------- Pillow banner ----------
import os
_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
_FONT_BOLD_PATH = os.path.join(_FONT_DIR, "Outfit-Bold.ttf")
_FONT_REG_PATH = os.path.join(_FONT_DIR, "Outfit-Regular.ttf")

def render_lightning_banner(reward_min: int = 300, reward_max: int = 800) -> io.BytesIO:
    try:
        from PIL import Image, ImageDraw, ImageFont
        w, h = 1000, 340
        img = Image.new("RGBA", (w, h), (15, 15, 30, 255))
        draw = ImageDraw.Draw(img)
        # dark gradient
        for y in range(h):
            t = y / h
            r = int(15 + t * 20)
            g = int(15 + t * 15)
            b = int(30 + t * 55)
            draw.line([(0, y), (w, y)], fill=(r, g, b, 255))
        # glow background — radial amarillo suave
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        cx, cy = 340, 170
        for radius in range(180, 0, -4):
            alpha = int(18 * (1 - radius / 180))
            gdraw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(255, 255, 100, alpha))
        img = Image.alpha_composite(img, glow)
        draw = ImageDraw.Draw(img)
        # THICK lightning bolt — polygon with width
        bolt_points = [
            (360, 20),   # top
            (400, 20),
            (385, 120),  # middle right
            (420, 115),
            (350, 310),  # bottom point
            (370, 310),
            (395, 180),  # back up
            (365, 185),
        ]
        draw.polygon(bolt_points, fill=(255, 255, 140, 255))
        # inner highlight
        bolt_inner = [
            (370, 35),
            (393, 35),
            (383, 115),
            (405, 112),
            (365, 290),
            (375, 290),
            (393, 170),
            (375, 173),
        ]
        draw.polygon(bolt_inner, fill=(255, 255, 220, 180))
        # outer glow bolt
        bolt_glow = [
            (345, 10), (415, 10), (400, 125), (435, 120),
            (340, 320), (380, 320), (405, 190), (355, 195),
        ]
        glow_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_overlay)
        glow_draw.polygon(bolt_glow, fill=(255, 255, 100, 35))
        img = Image.alpha_composite(img, glow_overlay)
        draw = ImageDraw.Draw(img)

        # fonts
        try:
            font_title = ImageFont.truetype(_FONT_BOLD_PATH, 64)
            font_sub = ImageFont.truetype(_FONT_REG_PATH, 24)
            font_reward = ImageFont.truetype(_FONT_BOLD_PATH, 28)
        except:
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()
            font_reward = ImageFont.load_default()

        # title
        tx = 520
        draw.text((tx, 80), "⚡ RELÁMPAGO ⚡", font=font_title, fill=(255, 255, 140, 255))
        draw.text((tx, 160), "¡El que lo ve lo pilla!", font=font_sub, fill=(220, 220, 255, 255))
        draw.text((tx, 200), "3 ganadores  •  5 minutos", font=font_sub, fill=(180, 180, 220, 255))
        # reward box
        draw.rounded_rectangle([tx, 250, tx + 340, 296], radius=14, fill=(255, 255, 100, 30), outline=(255, 255, 100, 120), width=2)
        draw.text((tx + 170, 260), f"{reward_min}-{reward_max} Coins + Boost x2", font=font_reward, fill=(255, 255, 140, 255), anchor="mt")

        # rounded corners
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=28, fill=255)
        card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        card.paste(img, (0, 0), mask)

        buf = io.BytesIO()
        card.convert("RGB").save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception:
        buf = io.BytesIO()
        buf.write(b"")
        buf.seek(0)
        return buf

class RelampagoView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=300)
        self.event_id = event_id
        self.claim_btn.custom_id = f"soulbot:relampago:{event_id}"

    @discord.ui.button(label="⚡ Reclamar (0/3)", style=discord.ButtonStyle.primary, custom_id="soulbot:relampago:0")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            eid = int(interaction.data["custom_id"].split(":")[-1])
        except:
            eid = self.event_id
        # fetch event
        cur = await db.db().execute("SELECT * FROM relampago_events WHERE id=?", (eid,))
        row = await cur.fetchone()
        if not row:
            await interaction.followup.send(embed=error_embed("Evento no encontrado o ya expirado."))
            return
        cols = [d[0] for d in cur.description]
        ev = dict(zip(cols, row))
        if ev["status"] != "active":
            await interaction.followup.send(embed=error_embed("Este relámpago ya expiró."))
            return
        # check 5m window
        try:
            ends = datetime.datetime.fromisoformat(ev["ends_at"])
            if datetime.datetime.utcnow() > ends:
                await db.db().execute("UPDATE relampago_events SET status='ended' WHERE id=?", (eid,))
                await db.db().commit()
                await interaction.followup.send(embed=error_embed("¡Tarde! El relámpago ya se fue (5 min)."))
                return
        except: pass
        # check winners <3
        cur2 = await db.db().execute("SELECT COUNT(*) FROM relampago_claims WHERE event_id=?", (eid,))
        cnt = (await cur2.fetchone())[0]
        if cnt >= 3:
            await interaction.followup.send(embed=error_embed("Ya hay 3 ganadores, se agotó."))
            return
        # check already claimed
        cur3 = await db.db().execute("SELECT 1 FROM relampago_claims WHERE event_id=? AND user_id=?", (eid, interaction.user.id))
        if await cur3.fetchone():
            await interaction.followup.send(embed=error_embed("Ya reclamaste este relámpago."))
            return
        # check nivel >=3
        try:
            data = await db.get_level_data(interaction.guild_id, interaction.user.id)
            if int(data.get("level", 0)) < 3:
                await interaction.followup.send(embed=error_embed(f"Necesitas nivel **3** (tienes {data.get('level',0)}). Habla un poco más."))
                return
        except: pass
        # award
        coins = random.randint(300, 800)
        # boost x2 30m
        expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=30)).isoformat()
        await db.add_coins(interaction.guild_id, interaction.user.id, coins, reason=f"relampago:{eid}")
        await db.set_user_multiplier(interaction.guild_id, interaction.user.id, 2.0, expires)
        await db.db().execute("INSERT INTO relampago_claims (event_id, user_id) VALUES (?, ?)", (eid, interaction.user.id))
        await db.db().commit()
        cur4 = await db.db().execute("SELECT COUNT(*) FROM relampago_claims WHERE event_id=?", (eid,))
        new_cnt = (await cur4.fetchone())[0]
        button.label = f"⚡ Reclamar ({new_cnt}/3)"
        if new_cnt >= 3:
            button.disabled = True
            button.style = discord.ButtonStyle.secondary
        await interaction.edit_original_response(view=self)
        await interaction.followup.send(embed=success_embed(f"¡Te llevaste el relámpago! ⚡\n+**{coins}** SoulCoins + **boost x2 30m**\nGanadores: {new_cnt}/3", title="⚡ ¡Reclamado!"))
        # update embed footer
        try:
            if interaction.message and interaction.message.embeds:
                emb = interaction.message.embeds[0]
                emb.set_footer(text=f"Evento #{eid} • {new_cnt}/3 reclamados • expira {ev['ends_at'][:16]} UTC")
                await interaction.message.edit(embed=emb, view=self)
        except: pass
        if new_cnt >= 3:
            await db.db().execute("UPDATE relampago_events SET status='ended' WHERE id=?", (eid,))
            await db.db().commit()

class RelampagoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spawn_loop.start()
        self.cleanup_loop.start()

    def cog_unload(self):
        try: self.spawn_loop.cancel()
        except: pass
        try: self.cleanup_loop.cancel()
        except: pass

    @tasks.loop(minutes=1)
    async def spawn_loop(self):
        try:
            await self.bot.wait_until_ready()
            cur = await db.db().execute("SELECT * FROM relampago_config WHERE enabled=1")
            rows = await cur.fetchall()
            if not rows:
                return
            cols = [d[0] for d in cur.description]
            for r in rows:
                cfg = dict(zip(cols, r))
                guild = self.bot.get_guild(cfg["guild_id"])
                if not guild:
                    continue
                # check if already active event
                cur2 = await db.db().execute("SELECT 1 FROM relampago_events WHERE guild_id=? AND status='active'", (cfg["guild_id"],))
                if await cur2.fetchone():
                    continue
                # check last_spawn + random interval
                last = cfg.get("last_spawn")
                now = datetime.datetime.utcnow()
                if last:
                    try:
                        last_dt = datetime.datetime.fromisoformat(last)
                        # random interval 1-4h from cfg
                        interval = random.randint(int(cfg["min_hours"]*60), int(cfg["max_hours"]*60))
                        if (now - last_dt).total_seconds() < interval*60:
                            continue
                    except: pass
                # spawn
                await self._spawn(guild, cfg)
                await asyncio.sleep(1)
        except Exception as e:
            try: print(f"[relampago] spawn_loop {e}")
            except: pass

    @tasks.loop(minutes=5)
    async def cleanup_loop(self):
        try:
            now = datetime.datetime.utcnow().isoformat()
            await db.db().execute("UPDATE relampago_events SET status='ended' WHERE status='active' AND ends_at <= ?", (now,))
            await db.db().commit()
        except: pass

    async def _spawn(self, guild: discord.Guild, cfg: dict):
        channel = guild.get_channel(cfg["channel_id"]) if cfg.get("channel_id") else None
        if not channel or not isinstance(channel, discord.TextChannel):
            # fallback to system channel
            channel = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
            if not channel:
                return
        ends_at = (datetime.datetime.utcnow() + datetime.timedelta(minutes=5)).isoformat()
        cur = await db.db().execute(
            "INSERT INTO relampago_events (guild_id, channel_id, ends_at, status) VALUES (?, ?, ?, 'active')",
            (guild.id, channel.id, ends_at)
        )
        await db.db().commit()
        eid = cur.lastrowid
        # update last_spawn
        await db.db().execute("UPDATE relampago_config SET last_spawn=? WHERE guild_id=?", (datetime.datetime.utcnow().isoformat(), guild.id))
        await db.db().commit()
        # build embed + pillow
        embed = base_embed(
            f"¡Un **relámpago** ha aparecido! ⚡\n"
            f"Pulsa **⚡ Reclamar** en los próximos **5 minutos**.\n"
            f"Máx **3** ganadores • Requiere **nivel 3**\n"
            f"Recompensa: **300-800** SoulCoins + **boost x2 30m**\n\n"
            f"*El que lo ve lo pilla — sin ping*",
            COLOR, title="⚡ ¡RELÁMPAGO!"
        )
        embed.set_footer(text=f"Evento #{eid} • 0/3 reclamados • expira en 5 min")
        view = RelampagoView(eid)
        try:
            self.bot.add_view(view)
        except: pass
        # pillow banner
        try:
            buf = await asyncio.to_thread(render_lightning_banner, 300, 800)
            file = discord.File(buf, filename="relampago.png") if buf.getbuffer().nbytes > 0 else None
            if file:
                embed.set_image(url="attachment://relampago.png")
                await channel.send(embed=embed, view=view, file=file)
            else:
                await channel.send(embed=embed, view=view)
        except Exception as e:
            try: print(f"[relampago] spawn send fail {e}")
            except: pass
            try:
                await channel.send(embed=embed, view=view)
            except: pass
        # auto-expire view after 5m
        await asyncio.sleep(300)
        try:
            await db.db().execute("UPDATE relampago_events SET status='ended' WHERE id=? AND status='active'", (eid,))
            await db.db().commit()
        except: pass

    relampago = app_commands.Group(name="relampago", description="Relámpagos 1-4h (Staff config)", default_permissions=discord.Permissions(manage_guild=True))

    @relampago.command(name="config", description="Configura canal y intervalo 1-4h del relámpago")
    @app_commands.describe(canal="Canal donde aparecerá (vacío = actual)", min_horas="Mín horas (1-4)", max_horas="Máx horas (1-4)")
    async def config(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None, min_horas: app_commands.Range[int,1,4]=1, max_horas: app_commands.Range[int,1,4]=4):
        if max_horas < min_horas:
            await interaction.response.send_message(embed=error_embed("max_horas debe ser ≥ min_horas"), ephemeral=True)
            return
        ch = canal or interaction.channel
        if not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message(embed=error_embed("Canal debe ser de texto."), ephemeral=True)
            return
        await db.db().execute(
            "INSERT INTO relampago_config (guild_id, channel_id, enabled, min_hours, max_hours, last_spawn) VALUES (?, ?, 1, ?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id=?, enabled=1, min_hours=?, max_hours=?",
            (interaction.guild_id, ch.id, min_horas, max_horas, datetime.datetime.utcnow().isoformat(), ch.id, min_horas, max_horas)
        )
        await db.db().commit()
        await interaction.response.send_message(embed=success_embed(f"Relámpago configurado en {ch.mention} cada **{min_horas}-{max_horas}h** aleatorio ⚡\nSilencioso con Pillow, 3 ganadores/5m, nivel 3.", title="⚡ Configurado"), ephemeral=True)

    @relampago.command(name="trigger", description="Fuerza un relámpago ahora (Staff)")
    async def trigger(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cur = await db.db().execute("SELECT * FROM relampago_config WHERE guild_id=?", (interaction.guild_id,))
        row = await cur.fetchone()
        if not row:
            await interaction.followup.send(embed=error_embed("Primero configura con /relampago config"), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        cfg = dict(zip(cols, row))
        # check active
        cur2 = await db.db().execute("SELECT 1 FROM relampago_events WHERE guild_id=? AND status='active'", (interaction.guild_id,))
        if await cur2.fetchone():
            await interaction.followup.send(embed=error_embed("Ya hay un relámpago activo, espera 5m."), ephemeral=True)
            return
        await self._spawn(interaction.guild, cfg)
        await interaction.followup.send(embed=success_embed("¡Relámpago lanzado! ⚡"), ephemeral=True)

    @relampago.command(name="disable", description="Desactiva relámpagos")
    async def disable(self, interaction: discord.Interaction):
        await db.db().execute("UPDATE relampago_config SET enabled=0 WHERE guild_id=?", (interaction.guild_id,))
        await db.db().commit()
        await interaction.response.send_message(embed=success_embed("Relámpagos desactivados."), ephemeral=True)

    @relampago.command(name="stats", description="Stats de relámpagos")
    async def stats(self, interaction: discord.Interaction):
        cur = await db.db().execute("SELECT COUNT(*) FROM relampago_events WHERE guild_id=?", (interaction.guild_id,))
        total = (await cur.fetchone())[0]
        cur2 = await db.db().execute("SELECT COUNT(*) FROM relampago_claims WHERE event_id IN (SELECT id FROM relampago_events WHERE guild_id=?)", (interaction.guild_id,))
        claims = (await cur2.fetchone())[0]
        await interaction.response.send_message(embed=base_embed(f"⚡ Eventos totales: **{total}**\n🎁 Reclamos: **{claims}**", COLOR, title="⚡ Stats Relámpago"), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RelampagoCog(bot))
