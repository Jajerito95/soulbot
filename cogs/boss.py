from __future__ import annotations
import datetime
import random
import os
import io
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

BOSS_SLAYER_COLOR = 0xE74C3C
BOSS_CHANNEL_ID = 1517597530022477965
BOSS_POST_INTERVAL = 5  # repostear cada 5 mensajes
BOSS_DAMAGE_MULTIPLIER = 5  # XP ganada × 5 = daño al boss

_font_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
_FONT_BOLD = os.path.join(_font_dir, "Outfit-Bold.ttf")
_FONT_REG = os.path.join(_font_dir, "Outfit-Regular.ttf")


async def damage_boss(guild_id: int, xp_amount: int) -> dict | None:
    """Aplica daño al boss activo: XP × multiplier. Retorna info del golpe o None."""
    if xp_amount <= 0:
        return None
    cur = await db.db().execute("SELECT * FROM boss_current WHERE guild_id=? AND status='active'", (guild_id,))
    row = await cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    boss = dict(zip(cols, row))
    dmg = xp_amount * BOSS_DAMAGE_MULTIPLIER
    new_hp = max(0, int(boss["current_hp"]) - dmg)
    await db.db().execute("UPDATE boss_current SET current_hp=? WHERE id=?", (new_hp, boss["id"]))
    # acumular daño por usuario (se pasará user_id desde el caller)
    return {"boss": boss, "damage": dmg, "new_hp": new_hp}


async def register_boss_damage(event_id: int, guild_id: int, user_id: int, damage: int):
    """Registra daño acumulado por usuario en el boss."""
    try:
        await db.db().execute(
            "INSERT INTO boss_damage (event_id, guild_id, user_id, damage) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(event_id, user_id) DO UPDATE SET damage=damage+?",
            (event_id, guild_id, user_id, damage, damage)
        )
        await db.db().commit()
    except Exception:
        try:
            await db.db().execute(
                "INSERT INTO boss_damage (event_id, guild_id, user_id, damage) VALUES (?, ?, ?, ?)",
                (event_id, guild_id, user_id, damage)
            )
            await db.db().commit()
        except Exception:
            pass


async def render_boss_pillow(boss_name: str, current_hp: int, max_hp: int,
                              top: list[tuple[str, int]], image_url: str | None,
                              total_damage_dealt: int) -> bytes | None:
    """Renderiza la tarjeta del boss con layout nuevo: nombre, imagen, HP, top3, recompensas."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        W, H = 934, 400
        BG = (20, 16, 16)
        accent = (231, 76, 60)
        accent_light = (255, 120, 100)

        base = Image.new("RGBA", (W, H), BG + (255,))
        bdraw = ImageDraw.Draw(base)
        for y in range(H):
            t = y / H
            bdraw.line([(0, y), (W, y)], fill=(int(20 + t * 30), int(16 + t * 10), int(16 + t * 10), 255))

        # diagonal accent rojo sutil
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.polygon([(W - 240, 0), (W, 0), (W, H), (W - 400, H)], fill=accent + (30,))
        base = Image.alpha_composite(base, overlay)

        # boss image left — 280x280
        img_x, img_y = 28, 60
        if image_url:
            try:
                data = await _download_boss(image_url)
                bimg = Image.open(io.BytesIO(data)).convert("RGBA").resize((280, 280), Image.LANCZOS)
                m = Image.new("L", (280, 280), 0)
                ImageDraw.Draw(m).rounded_rectangle([0, 0, 280, 280], radius=28, fill=255)
                base.paste(bimg, (img_x, img_y), m)
                ImageDraw.Draw(base).rounded_rectangle([img_x, img_y, img_x + 280, img_y + 280], radius=28, outline=accent + (180,), width=3)
            except Exception:
                pass

        # rounded corners
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, W, H], radius=28, fill=255)
        card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        card.paste(base, (0, 0), mask)
        draw = ImageDraw.Draw(card)

        try:
            font_title = ImageFont.truetype(_FONT_BOLD, 36)
            font_r = ImageFont.truetype(_FONT_REG, 20)
            font_s = ImageFont.truetype(_FONT_REG, 16)
            font_reward = ImageFont.truetype(_FONT_BOLD, 18)
            font_small = ImageFont.truetype(_FONT_REG, 14)
        except Exception:
            font_title = ImageFont.load_default()
            font_r = font_s = font_reward = font_small = font_title

        tx = 340 if image_url else 28

        # boss name
        draw.text((tx, 24), f"👹 {boss_name[:24]}", font=font_title, fill=(255, 255, 255, 255))

        # HP bar — thick
        pct = current_hp / max_hp if max_hp else 0
        bar_x, bar_y, bar_w, bar_h = tx, 80, W - tx - 28, 32
        draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=16, fill=(45, 40, 40, 255), outline=(60, 40, 40, 255), width=1)
        fill_w = int(bar_w * pct)
        if fill_w > 4:
            fimg = Image.new("RGBA", (fill_w, bar_h), (0, 0, 0, 0))
            fd = ImageDraw.Draw(fimg)
            for x in range(fill_w):
                t = x / max(1, fill_w)
                r = int(231 * (1 - t) + 255 * t)
                g = int(76 * (1 - t) + 100 * t)
                b = int(60 * (1 - t) + 60 * t)
                fd.line([(x, 0), (x, bar_h)], fill=(r, g, b, 255))
            fm = Image.new("L", (fill_w, bar_h), 0)
            ImageDraw.Draw(fm).rounded_rectangle([0, 0, fill_w, bar_h], radius=16, fill=255)
            if pct < 0.98:
                ImageDraw.Draw(fm).rectangle([fill_w - 16, 0, fill_w, bar_h], fill=255)
            card.paste(fimg, (bar_x, bar_y), fm)
        draw.text((bar_x + bar_w // 2, bar_y + 8), f"{current_hp:,} / {max_hp:,} HP", font=font_s, fill=(255, 255, 255, 255), anchor="mm")

        # damage dealt info
        draw.text((tx, 128), f"Daño total: {total_damage_dealt:,}", font=font_r, fill=accent + (255,))

        # top 3 damage
        draw.text((tx, 168), "⚔️ Top Daño:", font=font_r, fill=(255, 255, 255, 255))
        medal_colors = [(255, 215, 0), (192, 192, 192), (205, 127, 80)]
        y = 200
        for i, (name, dmg) in enumerate(top[:3]):
            mc = medal_colors[i] if i < 3 else (200, 200, 200)
            draw.ellipse([tx, y + 4, tx + 16, y + 20], fill=mc + (255,))
            draw.text((tx + 24, y), f"{name[:18]} — {dmg:,}", font=font_r,
                      fill=(255, 255, 255, 255) if i == 0 else (200, 200, 200, 255))
            y += 30

        # rewards box — right side
        rw_x = W - 220
        rw_y = 80
        draw.rounded_rectangle([rw_x, rw_y, W - 28, rw_y + 180], radius=16, fill=(30, 25, 25, 230), outline=accent + (80,), width=2)
        draw.text((rw_x + 96, rw_y + 12), "🎁 Recompensas", font=font_reward, fill=(255, 255, 255, 255), anchor="mt")
        rewards = [
            ("🥇 1er", "1,000 coins + 300 XP"),
            ("🥈 2do", "700 coins + 300 XP"),
            ("🥉 3ero", "500 coins + 300 XP"),
            ("Todos", "200 coins + 100 XP"),
        ]
        ry = rw_y + 42
        for label, value in rewards:
            draw.text((rw_x + 12, ry), label, font=font_small, fill=(255, 215, 0, 255) if "1er" in label else (192, 192, 192, 255) if "2do" in label else (205, 127, 80, 255) if "3ero" in label else (170, 173, 178, 255))
            draw.text((rw_x + 12, ry + 18), value, font=font_small, fill=(170, 173, 178, 255))
            ry += 38

        # footer
        draw.text((W // 2, H - 16), "SoulSeeker™ • Boss Semanal", font=font_small, fill=(110, 114, 120, 255), anchor="mm")

        buf = io.BytesIO()
        card.convert("RGB").save(buf, format="PNG")
        buf.seek(0)
        return buf.getvalue()
    except Exception as e:
        try:
            print(f"[boss] render_boss_pillow error: {e}", flush=True)
        except Exception:
            pass
        return None


async def _download_boss(url: str) -> bytes:
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()


class BossCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._msg_counter: dict[int, int] = {}  # guild_id -> message count since last post
        self._last_boss_msg: dict[int, discord.Message] = {}  # guild_id -> last boss embed msg

    boss = app_commands.Group(name="boss", description="Boss semanal")

    @boss.command(name="create", description="Crea el boss semanal (Staff)")
    @app_commands.describe(nombre="Nombre del boss", hp="HP total", imagen="URL imagen", canal="Canal donde aparecerá")
    async def create(self, interaction: discord.Interaction, nombre: str, hp: app_commands.Range[int, 1000, 1000000] = 100000, imagen: Optional[str] = None, canal: Optional[discord.TextChannel] = None):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        cur = await db.db().execute("SELECT 1 FROM boss_current WHERE guild_id=? AND status='active'", (interaction.guild_id,))
        if await cur.fetchone():
            await interaction.response.send_message(embed=error_embed("Ya hay un boss activo. Usa /boss end primero."), ephemeral=True)
            return
        target_ch = canal or interaction.channel
        if isinstance(target_ch, discord.TextChannel):
            await db.db().execute(
                "INSERT INTO boss_config (guild_id, channel_id, enabled) VALUES (?, ?, 1) "
                "ON CONFLICT(guild_id) DO UPDATE SET channel_id=?, enabled=1",
                (interaction.guild_id, target_ch.id, target_ch.id)
            )
            await db.db().commit()
        await db.db().execute(
            "INSERT INTO boss_current (guild_id, boss_name, max_hp, current_hp, image_url, status) "
            "VALUES (?, ?, ?, ?, ?, 'active')",
            (interaction.guild_id, nombre, hp, hp, imagen)
        )
        await db.db().commit()
        cur2 = await db.db().execute("SELECT id FROM boss_current WHERE guild_id=? AND status='active' ORDER BY id DESC LIMIT 1", (interaction.guild_id,))
        row2 = await cur2.fetchone()
        eid = row2[0] if row2 else 0

        # generar Pillow y enviar
        ch = target_ch if isinstance(target_ch, discord.TextChannel) else interaction.channel
        pillow = await render_boss_pillow(nombre, hp, hp, [], imagen, 0)
        file = discord.File(io.BytesIO(pillow), filename="boss.png") if pillow else None

        embed = base_embed(
            f"👹 **{nombre}** ha aparecido con **{hp:,} HP**\n"
            f"La daño se hace con **XP × 5** — ¡habla y sube de nivel!",
            COLOR, title="👹 Boss Semanal"
        )
        if imagen and not file:
            embed.set_image(url=imagen)
        if file:
            embed.set_image(url="attachment://boss.png")
        embed.set_footer(text=f"Boss ID {eid} • SoulSeeker™")

        try:
            msg = await ch.send(embed=embed, view=None, file=file) if file else await ch.send(embed=embed)
            self._last_boss_msg[interaction.guild_id] = msg
            self._msg_counter[interaction.guild_id] = 0
        except Exception:
            msg = await ch.send(embed=embed)
            self._last_boss_msg[interaction.guild_id] = msg

        await interaction.response.send_message(
            embed=success_embed(f"Boss **{nombre}** creado en {ch.mention} con **{hp:,} HP**\nDaño: XP × 5", title="👹 Boss creado"),
            ephemeral=True
        )

    @boss.command(name="end", description="Termina boss y reparte (Staff)")
    async def end(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        cur = await db.db().execute("SELECT * FROM boss_current WHERE guild_id=? AND status='active'", (interaction.guild_id,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("No hay boss activo."), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        boss = dict(zip(cols, row))
        await db.db().execute("UPDATE boss_current SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE id=?", (boss["id"],))
        await db.db().commit()
        await self._reward_boss(interaction.guild, boss["id"])
        await interaction.response.send_message(embed=success_embed(f"Boss **{boss['boss_name']}** finalizado.", title="👹 Boss terminado"))

    @boss.command(name="config", description="Configura canal auto del boss (Staff)")
    @app_commands.describe(canal="Canal donde aparecerá auto")
    async def config(self, interaction: discord.Interaction, canal: discord.TextChannel):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        await db.db().execute(
            "INSERT INTO boss_config (guild_id, channel_id, enabled) VALUES (?, ?, 1) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id=?, enabled=1",
            (interaction.guild_id, canal.id, canal.id)
        )
        await db.db().commit()
        await interaction.response.send_message(embed=success_embed(f"Canal boss configurado en {canal.mention} (auto).", title="⚙️ Boss Config"), ephemeral=True)

    @boss.command(name="stats", description="Stats del boss actual")
    async def stats(self, interaction: discord.Interaction):
        cur = await db.db().execute("SELECT * FROM boss_current WHERE guild_id=? AND status='active'", (interaction.guild_id,))
        row = await cur.fetchone()
        if not row:
            cur = await db.db().execute("SELECT * FROM boss_current WHERE guild_id=? ORDER BY id DESC LIMIT 1", (interaction.guild_id,))
            row = await cur.fetchone()
            if not row:
                await interaction.response.send_message(embed=error_embed("Sin boss aún."))
                return
            cols = [d[0] for d in cur.description]
            boss = dict(zip(cols, row))
            await interaction.response.send_message(embed=base_embed(
                f"Último boss **{boss['boss_name']}** — {boss['status']} — `{boss['current_hp']}/{boss['max_hp']} HP`",
                COLOR, title="👹 Boss Stats"
            ))
            return
        cols = [d[0] for d in cur.description]
        boss = dict(zip(cols, row))
        # Pillow
        cur2 = await db.db().execute("SELECT user_id, damage FROM boss_damage WHERE event_id=? ORDER BY damage DESC LIMIT 3", (boss["id"],))
        top_rows = await cur2.fetchall()
        top_names = []
        total_dmg = 0
        for uid, dmg in top_rows:
            m = interaction.guild.get_member(uid)
            name = m.display_name if m else f"User {uid}"
            top_names.append((name, dmg))
            total_dmg += dmg
        # total damage from all users
        cur3 = await db.db().execute("SELECT SUM(damage) FROM boss_damage WHERE event_id=?", (boss["id"],))
        total_row = await cur3.fetchone()
        total_all = (total_row[0] or 0) if total_row else 0

        pillow = await render_boss_pillow(
            boss["boss_name"], int(boss["current_hp"]), int(boss["max_hp"]),
            top_names, boss["image_url"], total_all
        )
        if pillow:
            file = discord.File(io.BytesIO(pillow), filename="boss.png")
            pct = (int(boss["current_hp"]) / int(boss["max_hp"]) * 100) if int(boss["max_hp"]) else 0
            bar = "▰" * int(12 * pct / 100) + "▱" * (12 - int(12 * pct / 100))
            embed = base_embed(f"{bar} `{boss['current_hp']:,}/{boss['max_hp']:,} HP` ({pct:.1f}%)", COLOR, title=f"👹 {boss['boss_name']}")
            embed.set_image(url="attachment://boss.png")
            await interaction.response.send_message(embed=embed, file=file)
            return
        # fallback
        pct = (int(boss["current_hp"]) / int(boss["max_hp"]) * 100) if int(boss["max_hp"]) else 0
        bar = "▰" * int(12 * pct / 100) + "▱" * (12 - int(12 * pct / 100))
        cur2 = await db.db().execute("SELECT user_id, damage FROM boss_damage WHERE event_id=? ORDER BY damage DESC LIMIT 3", (boss["id"],))
        top = await cur2.fetchall()
        top_lines = "\n".join([f"**{i + 1}.** <@{uid}> — {dmg:,}" for i, (uid, dmg) in enumerate(top)]) if top else "Nadie ha pegado aún."
        embed = base_embed(f"👹 **{boss['boss_name']}**\n{bar} `{boss['current_hp']:,}/{boss['max_hp']:,} HP` ({pct:.1f}%)\n\n**Top daño:**\n{top_lines}", COLOR, title="👹 Boss Stats")
        if boss["image_url"]:
            embed.set_image(url=boss["image_url"])
        await interaction.response.send_message(embed=embed)

    @boss.command(name="hp", description="HP del boss actual")
    async def hp(self, interaction: discord.Interaction):
        await self.stats(interaction)

    @boss.command(name="top", description="Top daño boss")
    async def top(self, interaction: discord.Interaction):
        cur = await db.db().execute("SELECT * FROM boss_current WHERE guild_id=? ORDER BY id DESC LIMIT 1", (interaction.guild_id,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("Sin boss aún."))
            return
        cols = [d[0] for d in cur.description]
        boss = dict(zip(cols, row))
        cur2 = await db.db().execute("SELECT user_id, damage FROM boss_damage WHERE event_id=? ORDER BY damage DESC LIMIT 10", (boss["id"],))
        rows = await cur2.fetchall()
        if not rows:
            await interaction.response.send_message(embed=error_embed("Nadie ha pegado aún."))
            return
        lines = [f"**{i + 1}.** <@{uid}> — **{dmg:,}**" for i, (uid, dmg) in enumerate(rows)]
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title=f"🏆 Top {boss['boss_name']}"))

    async def _handle_xp_damage(self, guild_id: int, user_id: int, xp_amount: int):
        """Llamado desde levels cog cuando se gana XP. Aplica daño × 5 al boss."""
        result = await damage_boss(guild_id, xp_amount)
        if not result:
            return
        boss = result["boss"]
        dmg = result["damage"]
        new_hp = result["new_hp"]
        await register_boss_damage(boss["id"], guild_id, user_id, dmg)

        # auto-repost card cada 5 mensajes
        count = self._msg_counter.get(guild_id, 0) + 1
        self._msg_counter[guild_id] = count

        if count >= BOSS_POST_INTERVAL:
            self._msg_counter[guild_id] = 0
            await self._repost_boss_card(guild_id, boss)

        if new_hp <= 0:
            await db.db().execute("UPDATE boss_current SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE id=?", (boss["id"],))
            await db.db().commit()
            await self._reward_boss_from_id(guild_id, boss["id"])

    async def _repost_boss_card(self, guild_id: int, boss: dict):
        """Regenera y edita el embed del boss con Pillow actualizado."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(BOSS_CHANNEL_ID)
        if not channel:
            return
        # top 3
        cur = await db.db().execute("SELECT user_id, damage FROM boss_damage WHERE event_id=? ORDER BY damage DESC LIMIT 3", (boss["id"],))
        top_rows = await cur.fetchall()
        top_names = []
        for uid, dmg in top_rows:
            m = guild.get_member(uid)
            name = m.display_name if m else f"User {uid}"
            top_names.append((name, dmg))
        # total damage
        cur2 = await db.db().execute("SELECT SUM(damage) FROM boss_damage WHERE event_id=?", (boss["id"],))
        total_row = await cur2.fetchone()
        total_all = (total_row[0] or 0) if total_row else 0

        pillow = await render_boss_pillow(
            boss["boss_name"], int(boss["current_hp"]), int(boss["max_hp"]),
            top_names, boss["image_url"], total_all
        )
        if not pillow:
            return

        file = discord.File(io.BytesIO(pillow), filename="boss.png")
        pct = (int(boss["current_hp"]) / int(boss["max_hp"]) * 100) if int(boss["max_hp"]) else 0
        bar = "▰" * int(12 * pct / 100) + "▱" * (12 - int(12 * pct / 100))
        embed = base_embed(
            f"👹 **{boss['boss_name']}**\n"
            f"{bar} `{boss['current_hp']:,}/{boss['max_hp']:,} HP` ({pct:.1f}%)\n"
            f"Daño: **XP × 5** — ¡habla para pegar!",
            COLOR, title="👹 Boss Semanal"
        )
        embed.set_image(url="attachment://boss.png")
        embed.set_footer(text=f"Boss ID {boss['id']} • SoulSeeker™")

        # intentar editar el último msg, si no, enviar nuevo
        last_msg = self._last_boss_msg.get(guild_id)
        if last_msg:
            try:
                await last_msg.edit(embed=embed, attachments=[file])
                return
            except Exception:
                pass
        try:
            msg = await channel.send(embed=embed, file=file)
            self._last_boss_msg[guild_id] = msg
        except Exception:
            pass

    async def _reward_boss_from_id(self, guild_id: int, event_id: int):
        guild = self.bot.get_guild(guild_id)
        if guild:
            await self._reward_boss(guild, event_id)

    async def _reward_boss(self, guild: discord.Guild, event_id: int):
        cur = await db.db().execute("SELECT user_id, damage FROM boss_damage WHERE event_id=? ORDER BY damage DESC", (event_id,))
        rows = await cur.fetchall()
        if not rows:
            return
        role = discord.utils.get(guild.roles, name="Boss Slayer")
        if not role:
            try:
                role = await guild.create_role(name="Boss Slayer", colour=discord.Colour(BOSS_SLAYER_COLOR), reason="Boss semanal")
                try:
                    bot_top = guild.me.top_role
                    await role.edit(position=max(1, bot_top.position - 1))
                except Exception:
                    pass
            except Exception:
                role = None
        for i, (uid, dmg) in enumerate(rows):
            member = guild.get_member(uid)
            if not member:
                try:
                    member = await guild.fetch_member(uid)
                except Exception:
                    continue
            coins = 1000 if i == 0 else 700 if i == 1 else 500 if i == 2 else 200
            await db.add_coins(guild.id, uid, coins, reason=f"boss:{event_id} rank {i + 1}")
            from utils.levels_engine import award_xp
            try:
                await award_xp(guild, member, 300 if i < 3 else 100, _boss_reward=True)
            except Exception:
                pass
            if role:
                try:
                    if role not in member.roles:
                        await member.add_roles(role, reason="Boss Slayer")
                except Exception:
                    pass
        print(f"[boss] rewarded {len(rows)} for {event_id}", flush=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BossCog(bot))
