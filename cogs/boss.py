from __future__ import annotations
import datetime
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

BOSS_HP_DEFAULT = 100000
BOSS_SLAYER_COLOR = 0xFF1A1A  # rojo fuerte

class BossCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    boss = app_commands.Group(name="boss", description="Boss semanal votado (Staff)", default_permissions=discord.Permissions(manage_guild=True))

    @boss.command(name="create", description="Crea el boss semanal votado (Staff)")
    @app_commands.describe(nombre="Nombre del boss", hp="HP total (ej 100000)", imagen="URL imagen del boss (opcional)")
    async def create(self, interaction: discord.Interaction, nombre: str, hp: app_commands.Range[int,1000,1000000]=100000, imagen: Optional[str]=None):
        # solo staff puede crear
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        # check if already active
        cur = await db.db().execute("SELECT 1 FROM boss_current WHERE guild_id=? AND status='active'", (interaction.guild_id,))
        if await cur.fetchone():
            await interaction.response.send_message(embed=error_embed("Ya hay un boss activo. Usa /boss end primero."), ephemeral=True)
            return
        await db.db().execute("INSERT INTO boss_current (guild_id, boss_name, max_hp, current_hp, image_url, status) VALUES (?, ?, ?, ?, ?, 'active')", (interaction.guild_id, nombre, hp, hp, imagen))
        await db.db().commit()
        embed = base_embed(f"👹 **{nombre}** ha aparecido con **{hp:,} HP**\nAtaca con `/boss attack`\nHP colectivo — ¡todos pegan!", COLOR, title="👹 Boss Semanal ¡Votado!")
        if imagen:
            embed.set_image(url=imagen)
        embed.set_footer(text="Boss votado por Staff • SoulSeeker™")
        await interaction.response.send_message(embed=embed)

    @boss.command(name="attack", description="Ataca al boss semanal")
    @app_commands.describe(cantidad="Daño: 100-500 (o deja vacío para random)")
    async def attack(self, interaction: discord.Interaction, cantidad: Optional[app_commands.Range[int,100,500]]=None):
        cur = await db.db().execute("SELECT * FROM boss_current WHERE guild_id=? AND status='active'", (interaction.guild_id,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("No hay boss activo. Espera al siguiente votado."), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        boss = dict(zip(cols, row))
        dmg = cantidad or random.randint(100, 500)
        # aplica daño
        new_hp = max(0, int(boss["current_hp"]) - dmg)
        await db.db().execute("UPDATE boss_current SET current_hp=? WHERE id=?", (new_hp, boss["id"]))
        # registra daño por user
        await db.db().execute("INSERT INTO boss_damage (event_id, guild_id, user_id, damage) VALUES (?, ?, ?, ?) ON CONFLICT(event_id, user_id) DO UPDATE SET damage=damage+?", (boss["id"], interaction.guild_id, interaction.user.id, dmg, dmg))
        # si no existe tabla con ON CONFLICT, fallback
        try:
            await db.db().commit()
        except:
            await db.db().execute("INSERT INTO boss_damage (event_id, guild_id, user_id, damage) VALUES (?, ?, ?, ?)", (boss["id"], interaction.guild_id, interaction.user.id, dmg))
            await db.db().commit()
        if new_hp <= 0:
            await db.db().execute("UPDATE boss_current SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE id=?", (boss["id"],))
            await db.db().commit()
            # recompensas
            await self._reward_boss(interaction.guild, boss["id"])
            await interaction.response.send_message(embed=success_embed(f"💥 ¡Golpe final! **{dmg}** daño — **{boss['boss_name']}** derrotado!\nRecompensas repartidas a todos los que pegaron + Top 3 extra.", title="👹 ¡BOSS CAÍDO!"))
            return
        # barra
        pct = (new_hp / int(boss["max_hp"]) * 100)
        bar_len = 12
        filled = int(bar_len * new_hp / int(boss["max_hp"]))
        bar = "▰"*filled + "▱"*(bar_len-filled)
        await interaction.response.send_message(embed=base_embed(f"⚔️ {interaction.user.mention} pegó **{dmg}**\n{bar} `{new_hp:,}/{boss['max_hp']:,} HP` ({pct:.1f}%)", COLOR, title=f"👹 {boss['boss_name']}"))

    @boss.command(name="hp", description="Mira el HP del boss actual")
    async def hp(self, interaction: discord.Interaction):
        cur = await db.db().execute("SELECT * FROM boss_current WHERE guild_id=? AND status='active'", (interaction.guild_id,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("No hay boss activo."))
            return
        cols = [d[0] for d in cur.description]
        boss = dict(zip(cols, row))
        pct = (int(boss["current_hp"]) / int(boss["max_hp"]) * 100)
        bar = "▰"*int(12*pct/100) + "▱"*(12-int(12*pct/100))
        embed = base_embed(f"👹 **{boss['boss_name']}**\n{bar} `{boss['current_hp']:,}/{boss['max_hp']:,} HP` ({pct:.1f}%)", COLOR, title="👹 Boss HP")
        if boss["image_url"]:
            embed.set_image(url=boss["image_url"])
        await interaction.response.send_message(embed=embed)

    @boss.command(name="top", description="Top daño al boss actual")
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
            await interaction.response.send_message(embed=error_embed("Nadie ha pegado aún. Usa /boss attack"))
            return
        lines = [f"**{i+1}.** <@{uid}> — **{dmg:,}** daño" for i,(uid,dmg) in enumerate(rows)]
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title=f"🏆 Top Daño {boss['boss_name']}"))

    @boss.command(name="end", description="Termina boss y reparte recompensas (Staff)")
    async def end(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        cur = await db.db().execute("SELECT * FROM boss_current WHERE guild_id=? AND status='active'", (interaction.guild_id,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("No hay boss activo."))
            return
        cols = [d[0] for d in cur.description]
        boss = dict(zip(cols, row))
        await db.db().execute("UPDATE boss_current SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE id=?", (boss["id"],))
        await db.db().commit()
        await self._reward_boss(interaction.guild, boss["id"])
        await interaction.response.send_message(embed=success_embed(f"Boss **{boss['boss_name']}** finalizado y recompensas entregadas.", title="👹 Boss terminado"))

    async def _reward_boss(self, guild: discord.Guild, event_id: int):
        # top daño + todos
        cur = await db.db().execute("SELECT user_id, damage FROM boss_damage WHERE event_id=? ORDER BY damage DESC", (event_id,))
        rows = await cur.fetchall()
        if not rows:
            return
        # crea/asegura rol Boss Slayer rojo fuerte por encima de colores
        role = discord.utils.get(guild.roles, name="Boss Slayer")
        if not role:
            try:
                role = await guild.create_role(name="Boss Slayer", colour=discord.Colour(BOSS_SLAYER_COLOR), reason="Boss semanal")
                # intenta ponerlo alto (por encima de roles de colores, pero debajo de bot)
                try:
                    # coloca justo debajo del bot
                    bot_top = guild.me.top_role
                    await role.edit(position=max(1, bot_top.position - 1))
                except: pass
            except: role = None
        # reparte
        for i, (uid, dmg) in enumerate(rows):
            member = guild.get_member(uid)
            if not member:
                try: member = await guild.fetch_member(uid)
                except: continue
            coins = 1000 if i==0 else 700 if i==1 else 500 if i==2 else 200
            await db.add_coins(guild.id, uid, coins, reason=f"boss:{event_id} rank {i+1}")
            # XP
            from utils.levels_engine import award_xp
            try: await award_xp(guild, member, 300 if i<3 else 100)
            except: pass
            # rol a todos los que pegaron (pero top 3 ya lo tienen, todos lo reciben)
            if role:
                try:
                    if role not in member.roles:
                        await member.add_roles(role, reason="Boss Slayer")
                except: pass
        # también asegura que top 3 tengan rol aunque ya se dio a todos, el rol es para todos los que pegaron
        print(f"[boss] rewarded {len(rows)} players for event {event_id}", flush=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(BossCog(bot))
