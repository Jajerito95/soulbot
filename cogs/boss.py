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

BOSS_SLAYER_COLOR = 0xE74C3C

class BossAttackView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.attack_btn.custom_id = f"soulbot:boss:{event_id}"

    @discord.ui.button(label="⚔️ Atacar (100-500)", style=discord.ButtonStyle.danger, custom_id="soulbot:boss:0")
    async def attack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            eid = int(interaction.data["custom_id"].split(":")[-1])
        except:
            eid = self.event_id
        cog = interaction.client.get_cog("BossCog")
        if cog:
            await cog._handle_attack(interaction, eid)

class BossCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    boss = app_commands.Group(name="boss", description="Boss semanal")

    @boss.command(name="create", description="Crea el boss semanal (Staff)")
    @app_commands.describe(nombre="Nombre del boss", hp="HP total", imagen="URL imagen", canal="Canal donde aparecerá")
    async def create(self, interaction: discord.Interaction, nombre: str, hp: app_commands.Range[int,1000,1000000]=100000, imagen: Optional[str]=None, canal: Optional[discord.TextChannel]=None):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        cur = await db.db().execute("SELECT 1 FROM boss_current WHERE guild_id=? AND status='active'", (interaction.guild_id,))
        if await cur.fetchone():
            await interaction.response.send_message(embed=error_embed("Ya hay un boss activo. Usa /boss end primero."), ephemeral=True)
            return
        target_ch = canal or interaction.channel
        if isinstance(target_ch, discord.TextChannel):
            await db.db().execute("INSERT INTO boss_config (guild_id, channel_id, enabled) VALUES (?, ?, 1) ON CONFLICT(guild_id) DO UPDATE SET channel_id=?, enabled=1", (interaction.guild_id, target_ch.id, target_ch.id))
            await db.db().commit()
        await db.db().execute("INSERT INTO boss_current (guild_id, boss_name, max_hp, current_hp, image_url, status) VALUES (?, ?, ?, ?, ?, 'active')", (interaction.guild_id, nombre, hp, hp, imagen))
        await db.db().commit()
        cur2 = await db.db().execute("SELECT id FROM boss_current WHERE guild_id=? AND status='active' ORDER BY id DESC LIMIT 1", (interaction.guild_id,))
        row2 = await cur2.fetchone()
        eid = row2[0] if row2 else 0
        embed = base_embed(f"👹 **{nombre}** ha aparecido con **{hp:,} HP**\nPulsa **⚔️ Atacar** para hacer daño (HP colectivo)\n¡Todos pegan!", COLOR, title="👹 Boss Semanal ¡Votado!")
        if imagen:
            embed.set_image(url=imagen)
        embed.set_footer(text=f"Boss votado por Staff • ID {eid} • SoulSeeker™")
        view = BossAttackView(eid)
        try:
            self.bot.add_view(view)
        except: pass
        ch = target_ch if isinstance(target_ch, discord.TextChannel) else interaction.channel
        try:
            await ch.send(embed=embed, view=view)
            await interaction.response.send_message(embed=success_embed(f"Boss **{nombre}** creado en {ch.mention} con **{hp:,} HP**", title="👹 Boss creado"), ephemeral=True)
        except:
            await interaction.response.send_message(embed=embed, view=view)

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
        await db.db().execute("INSERT INTO boss_config (guild_id, channel_id, enabled) VALUES (?, ?, 1) ON CONFLICT(guild_id) DO UPDATE SET channel_id=?, enabled=1", (interaction.guild_id, canal.id, canal.id))
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
            await interaction.response.send_message(embed=base_embed(f"Último boss **{boss['boss_name']}** — {boss['status']} — `{boss['current_hp']}/{boss['max_hp']} HP`", COLOR, title="👹 Boss Stats"))
            return
        cols = [d[0] for d in cur.description]
        boss = dict(zip(cols, row))
        pct = (int(boss["current_hp"]) / int(boss["max_hp"]) * 100) if int(boss["max_hp"]) else 0
        bar = "▰"*int(12*pct/100) + "▱"*(12-int(12*pct/100))
        cur2 = await db.db().execute("SELECT user_id, damage FROM boss_damage WHERE event_id=? ORDER BY damage DESC LIMIT 3", (boss["id"],))
        top = await cur2.fetchall()
        top_lines = "\n".join([f"**{i+1}.** <@{uid}> — {dmg:,}" for i,(uid,dmg) in enumerate(top)]) if top else "Nadie ha pegado aún."
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
        lines = [f"**{i+1}.** <@{uid}> — **{dmg:,}**" for i,(uid,dmg) in enumerate(rows)]
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title=f"🏆 Top {boss['boss_name']}"))

    async def _handle_attack(self, interaction: discord.Interaction, event_id: int):
        cur = await db.db().execute("SELECT * FROM boss_current WHERE id=? AND status='active'", (event_id,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(embed=error_embed("Boss ya no está activo."), ephemeral=True)
            return
        cols = [d[0] for d in cur.description]
        boss = dict(zip(cols, row))
        dmg = random.randint(100, 500)
        new_hp = max(0, int(boss["current_hp"]) - dmg)
        await db.db().execute("UPDATE boss_current SET current_hp=? WHERE id=?", (new_hp, boss["id"]))
        try:
            await db.db().execute("INSERT INTO boss_damage (event_id, guild_id, user_id, damage) VALUES (?, ?, ?, ?) ON CONFLICT(event_id, user_id) DO UPDATE SET damage=damage+?", (boss["id"], boss["guild_id"], interaction.user.id, dmg, dmg))
            await db.db().commit()
        except:
            await db.db().execute("INSERT INTO boss_damage (event_id, guild_id, user_id, damage) VALUES (?, ?, ?, ?)", (boss["id"], boss["guild_id"], interaction.user.id, dmg))
            await db.db().commit()
        if new_hp <= 0:
            await db.db().execute("UPDATE boss_current SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE id=?", (boss["id"],))
            await db.db().commit()
            await self._reward_boss(interaction.guild, boss["id"])
            await interaction.response.send_message(embed=success_embed(f"💥 ¡Golpe final! **{dmg}** — **{boss['boss_name']}** caído! Recompensas a todos.", title="👹 ¡BOSS CAÍDO!"))
            return
        pct = (new_hp / int(boss["max_hp"]) * 100)
        bar = "▰"*int(12*pct/100) + "▱"*(12-int(12*pct/100))
        try:
            if interaction.message and interaction.message.embeds:
                emb = interaction.message.embeds[0]
                emb.description = f"👹 **{boss['boss_name']}**\n{bar} `{new_hp:,}/{boss['max_hp']:,} HP` ({pct:.1f}%)\nPulsa **⚔️ Atacar**"
                await interaction.response.edit_message(embed=emb, view=BossAttackView(event_id))
                await interaction.followup.send(embed=success_embed(f"Pegaste **{dmg}** — {bar} `{new_hp:,}` HP", title="⚔️ ¡Ataque!"), ephemeral=True)
                return
        except:
            pass
        await interaction.response.send_message(embed=base_embed(f"⚔️ Pegaste **{dmg}**\n{bar} `{new_hp:,}/{boss['max_hp']:,} HP` ({pct:.1f}%)", COLOR, title=f"👹 {boss['boss_name']}"), ephemeral=True)

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
                except: pass
            except: role = None
        for i, (uid, dmg) in enumerate(rows):
            member = guild.get_member(uid)
            if not member:
                try: member = await guild.fetch_member(uid)
                except: continue
            coins = 1000 if i==0 else 700 if i==1 else 500 if i==2 else 200
            await db.add_coins(guild.id, uid, coins, reason=f"boss:{event_id} rank {i+1}")
            from utils.levels_engine import award_xp
            try: await award_xp(guild, member, 300 if i<3 else 100)
            except: pass
            if role:
                try:
                    if role not in member.roles:
                        await member.add_roles(role, reason="Boss Slayer")
                except: pass
        print(f"[boss] rewarded {len(rows)} for {event_id}", flush=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(BossCog(bot))
