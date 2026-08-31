from __future__ import annotations
import asyncio
import datetime
import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

DAILY_MIN, DAILY_MAX = 100, 250
DAILY_COOLDOWN_HOURS = 24


def _seconds_to_human(seconds: int) -> str:
    if seconds >= 31536000:
        return f"{seconds // 31536000} año(s)"
    if seconds >= 2592000:
        return f"{seconds // 2592000} mes(es)"
    if seconds >= 604800:
        return f"{seconds // 604800} semana(s)"
    if seconds >= 86400:
        return f"{seconds // 86400} día(s)"
    if seconds >= 3600:
        return f"{seconds // 3600} hora(s)"
    return f"{seconds // 60} minuto(s)"


JOBS = {"minero": 1500, "pescador": 1000}
WORK_COOLDOWN = 30 * 60  # 30m


class MinerView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=20)
        self.author_id = author_id
        self.clicked: set[int] = set()
        self.success = False
        for i in range(5):
            btn = discord.ui.Button(label="🪨", style=discord.ButtonStyle.secondary, custom_id=f"mine_{i}")
            # closure con defaults para capturar i y btn correctamente
            async def _cb(interaction: discord.Interaction, idx=i, b=btn):
                if interaction.user.id != self.author_id:
                    await interaction.response.send_message(embed=error_embed("Solo tú puedes picar tus rocas."), ephemeral=True)
                    return
                if idx in self.clicked:
                    await interaction.response.defer()
                    return
                self.clicked.add(idx)
                b.disabled = True
                b.label = "✅"
                b.style = discord.ButtonStyle.success
                if len(self.clicked) >= 5:
                    self.success = True
                    self.stop()
                    await interaction.response.edit_message(content="⛏️ ¡Todas las rocas picadas! Reclama tu recompensa.", view=self)
                else:
                    await interaction.response.edit_message(view=self)
            btn.callback = _cb  # type: ignore
            self.add_item(btn)


class FisherView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.phase = 0  # 0 lanzar, 1 esperando, 2 pica
        self.success = False
        self._bite_time: float = 0

    @discord.ui.button(label="🎣 Lanzar caña", style=discord.ButtonStyle.primary)
    async def launch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("Solo tú puedes pescar."), ephemeral=True)
            return
        if self.phase == 0:
            self.phase = 1
            button.label = "⏳ Esperando picada..."
            button.disabled = True
            button.style = discord.ButtonStyle.secondary
            await interaction.response.edit_message(content="`Lanzaste la caña... esperando picada 2-4s`", view=self)
            await asyncio.sleep(random.randint(2, 4))
            if self.is_finished():
                return
            self.phase = 2
            button.label = "¡TIRA AHORA! 🎣"
            button.style = discord.ButtonStyle.success
            button.disabled = False
            self._bite_time = time.time()
            try:
                await interaction.message.edit(content="🐟 ¡Pica! ¡Clicka rápido! (3s)", view=self)
            except discord.NotFound:
                return
            await asyncio.sleep(3)
            if not self.success and not self.is_finished():
                self.stop()
                button.label = "💨 Se escapó..."
                button.disabled = True
                button.style = discord.ButtonStyle.danger
                try:
                    await interaction.message.edit(content="💨 Se escapó el pez... inténtalo de nuevo.", view=self)
                except Exception:
                    pass
        elif self.phase == 2:
            # segundo click = tirar
            if time.time() - self._bite_time <= 3:
                self.success = True
                self.stop()
                button.label = "✅ ¡Pescado!"
                button.disabled = True
                button.style = discord.ButtonStyle.success
                await interaction.response.edit_message(content="🎣 ¡Pescado atrapado!", view=self)
            else:
                await interaction.response.send_message(embed=error_embed("Demasiado tarde."), ephemeral=True)


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.prune_loop.start()

    def cog_unload(self):
        try: self.prune_loop.cancel()
        except: pass

    @tasks.loop(hours=24)
    async def prune_loop(self):
        # Poda transacciones >30d para no inflar la DB Turso
        try:
            await self.bot.wait_until_ready()
            import database as db
            await db.db().execute("DELETE FROM economy_transactions WHERE julianday('now') - julianday(created_at) > 30")
            await db.db().commit()
        except Exception:
            pass

    @prune_loop.before_loop
    async def before_prune(self):
        await self.bot.wait_until_ready()

    # ---------- comandos de miembro ----------

    @app_commands.command(name="balance", description="Muestra tus SoulCoins o los de otro usuario")
    @app_commands.describe(usuario="Usuario a consultar (opcional)")
    async def balance(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        target = usuario or interaction.user
        coins = await db.get_balance(interaction.guild_id, target.id)
        embed = base_embed(f"💰 **{coins}** SoulCoins", COLOR, title=f"👛 Cartera de {target.display_name}")
        embed.set_thumbnail(url=target.display_avatar.url)
        try:
            from utils.card_renderer import render_profile
            buf = await render_profile(target.display_name, target.display_avatar.url, coins)
            file = discord.File(buf, filename="profile.png")
            embed.set_image(url="attachment://profile.png")
            await interaction.response.send_message(embed=embed, file=file)
        except Exception:
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Reclama tu recompensa diaria de SoulCoins")
    async def daily(self, interaction: discord.Interaction):
        last = await db.get_last_daily(interaction.guild_id, interaction.user.id)
        now = datetime.datetime.utcnow()

        if last:
            last_dt = datetime.datetime.fromisoformat(last)
            elapsed = now - last_dt
            if elapsed < datetime.timedelta(hours=DAILY_COOLDOWN_HOURS):
                remaining = datetime.timedelta(hours=DAILY_COOLDOWN_HOURS) - elapsed
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                await interaction.response.send_message(
                    embed=error_embed(f"Ya reclamaste tu daily. Vuelve en **{hours}h {minutes}m**."), ephemeral=True
                )
                return

        import random
        config = await db.get_guild_config(interaction.guild_id)
        amount = random.randint(config["daily_min"], config["daily_max"])
        new_balance = await db.add_coins(interaction.guild_id, interaction.user.id, amount)
        await db.set_last_daily(interaction.guild_id, interaction.user.id, now.isoformat())

        await interaction.response.send_message(
            embed=success_embed(f"💰 Has recibido **{amount}** SoulCoins.\n👛 Saldo actual: **{new_balance}**", title="🎁 Daily reclamado")
        )

    @app_commands.command(name="work", description="Trabaja con minijuego (minero/pescador)")
    @app_commands.describe(trabajo="Elige tu trabajo")
    @app_commands.choices(trabajo=[
        app_commands.Choice(name="⛏️ Minero — 1.500 SoulCoins (pica 5 rocas)", value="minero"),
        app_commands.Choice(name="🎣 Pescador — 1.000 SoulCoins (timing)", value="pescador"),
    ])
    async def work(self, interaction: discord.Interaction, trabajo: app_commands.Choice[str]):
        job = trabajo.value
        reward = JOBS[job]
        # cooldown 30m
        last = await db.get_work_last(interaction.guild_id, interaction.user.id, job)
        if last:
            try:
                last_dt = datetime.datetime.fromisoformat(last)
                elapsed = (datetime.datetime.utcnow() - last_dt).total_seconds()
                if elapsed < WORK_COOLDOWN:
                    rem = int(WORK_COOLDOWN - elapsed)
                    await interaction.response.send_message(
                        embed=error_embed(f"Estás cansado de **{job}**. Vuelve en **{rem//60}m {rem%60}s**."), ephemeral=True
                    )
                    return
            except Exception:
                pass
        # también cooldown global (cualquier trabajo) para evitar spam
        # si quieres global, descomenta:
        # for j in JOBS:
        #     if j != job:
        #         last2 = await db.get_work_last(interaction.guild_id, interaction.user.id, j)
        #         ...

        await interaction.response.defer(ephemeral=True)
        if job == "minero":
            view = MinerView(interaction.user.id)
            await interaction.followup.send(content=f"⛏️ **Minero** — pica las 5 rocas en 20s por **{reward}** SoulCoins!", view=view, ephemeral=True)
            await view.wait()
            if view.success and len(view.clicked) >= 5:
                new_bal = await db.add_coins(interaction.guild_id, interaction.user.id, reward, reason=f"work:{job}")
                await db.set_work_last(interaction.guild_id, interaction.user.id, job)
                await interaction.followup.send(embed=success_embed(f"⛏️ ¡Trabajo completado! +**{reward}** SoulCoins\n👛 Saldo: **{new_bal}**"), ephemeral=True)
            else:
                await interaction.followup.send(embed=error_embed("No completaste las 5 rocas a tiempo. Inténtalo de nuevo (sin cooldown)."), ephemeral=True)
        else:  # pescador
            view = FisherView(interaction.user.id)
            await interaction.followup.send(content=f"🎣 **Pescador** — lanza y tira a tiempo por **{reward}** SoulCoins!", view=view, ephemeral=True)
            await view.wait()
            if view.success:
                new_bal = await db.add_coins(interaction.guild_id, interaction.user.id, reward, reason=f"work:{job}")
                await db.set_work_last(interaction.guild_id, interaction.user.id, job)
                await interaction.followup.send(embed=success_embed(f"🎣 ¡Pesca perfecta! +**{reward}** SoulCoins\n👛 Saldo: **{new_bal}**"), ephemeral=True)
            else:
                # si falló por timeout, el view ya editó el mensaje a "Se escapó..."
                if not view.is_finished() or not view.success:
                    try:
                        await interaction.followup.send(embed=error_embed("Se escapó el pez... inténtalo de nuevo (sin cooldown)."), ephemeral=True)
                    except Exception:
                        pass

    @app_commands.command(name="pay", description="Transfiere SoulCoins a otro usuario")
    @app_commands.describe(usuario="Usuario que recibe las coins", cantidad="Cantidad a transferir")
    async def pay(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: app_commands.Range[int, 1, None]):
        if usuario.id == interaction.user.id:
            await interaction.response.send_message(embed=error_embed("No puedes pagarte a ti mismo."), ephemeral=True)
            return
        if usuario.bot:
            await interaction.response.send_message(embed=error_embed("No puedes pagarle a un bot."), ephemeral=True)
            return

        balance = await db.get_balance(interaction.guild_id, interaction.user.id)
        if balance < cantidad:
            await interaction.response.send_message(embed=error_embed(f"No tienes suficientes SoulCoins. Tu saldo: **{balance}**"), ephemeral=True)
            return

        await db.add_coins(interaction.guild_id, interaction.user.id, -cantidad)
        await db.add_coins(interaction.guild_id, usuario.id, cantidad)

        await interaction.response.send_message(
            embed=success_embed(f"💸 {interaction.user.mention} le pagó **{cantidad}** SoulCoins a {usuario.mention}.")
        )

    @app_commands.command(name="richest", description="Top 10 SoulCoins del servidor")
    async def richest(self, interaction: discord.Interaction):
        rows = await db.get_economy_leaderboard(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(embed=error_embed("Todavía no hay SoulCoins en circulación."))
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"{medals[i] if i < 3 else f'`#{i+1}`'} <@{r[0]}> — **{r[1]}** 💰" for i, r in enumerate(rows)]
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title="🏆 Top SoulCoins"))

    # ---------- tienda ----------

    @app_commands.command(name="shop", description="Muestra la tienda de SoulCoins del servidor")
    async def shop(self, interaction: discord.Interaction):
        items = await db.get_shop_items(interaction.guild_id)
        if not items:
            await interaction.response.send_message(embed=error_embed("La tienda está vacía. El Staff aún no ha añadido artículos."))
            return

        icons = {"role": "🎭", "temprole": "⏱️", "boost": "⚡", "xp": "⭐"}
        lines = []
        for item in items:
            if item["type"] == "role":
                detail = f"🎭 Rol permanente <@&{item['role_id']}>"
            elif item["type"] == "temprole":
                detail = f"⏱️ Rol temporal <@&{item['role_id']}> por {_seconds_to_human(item['temprole_seconds'])}"
            elif item["type"] == "xp":
                detail = f"⭐ +{item['xp_amount']} XP instantánea"
            else:
                detail = f"⚡ Boost x{item['boost_multiplier']} por {item['boost_minutes']} min"
            lines.append(f"{icons.get(item['type'], '•')} `#{item['id']}` **{item['name']}** — 💰 {item['price']}\n{detail}")

        embed = base_embed("\n\n".join(lines), COLOR, title="🛒 Tienda SoulSeeker™")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Compra un artículo de la tienda")
    @app_commands.describe(item_id="ID del artículo (mira /shop)")
    async def buy(self, interaction: discord.Interaction, item_id: int):
        item = await db.get_shop_item(interaction.guild_id, item_id)
        if not item:
            await interaction.response.send_message(embed=error_embed("Ese artículo no existe."), ephemeral=True)
            return

        balance = await db.get_balance(interaction.guild_id, interaction.user.id)
        if balance < item["price"]:
            await interaction.response.send_message(
                embed=error_embed(f"Te faltan **{item['price'] - balance}** SoulCoins para comprarlo."), ephemeral=True
            )
            return

        if item["type"] == "role":
            role = interaction.guild.get_role(item["role_id"])
            if not role:
                await interaction.response.send_message(embed=error_embed("El rol de este artículo ya no existe. Avisa al Staff."), ephemeral=True)
                return
            if role in interaction.user.roles:
                await interaction.response.send_message(embed=error_embed("Ya tienes ese rol."), ephemeral=True)
                return
            await db.add_coins(interaction.guild_id, interaction.user.id, -item["price"])
            await interaction.user.add_roles(role, reason="Compra en la tienda de SoulCoins")
            await interaction.response.send_message(embed=success_embed(f"🎉 Compraste **{item['name']}** — {role.mention} añadido."))

        elif item["type"] == "temprole":
            role = interaction.guild.get_role(item["role_id"])
            if not role:
                await interaction.response.send_message(embed=error_embed("El rol de este artículo ya no existe. Avisa al Staff."), ephemeral=True)
                return
            await db.add_coins(interaction.guild_id, interaction.user.id, -item["price"])
            expires = (datetime.datetime.utcnow() + datetime.timedelta(seconds=item["temprole_seconds"])).isoformat()
            try:
                await interaction.user.add_roles(role, reason="Compra en la tienda de SoulCoins (rol temporal)")
            except discord.Forbidden:
                await interaction.response.send_message(embed=error_embed("No pude asignarte el rol. Avisa al Staff."), ephemeral=True)
                return
            await db.add_temp_role(interaction.guild_id, interaction.user.id, role.id, expires, self.bot.user.id)
            ts = int(datetime.datetime.fromisoformat(expires).timestamp())
            await interaction.response.send_message(
                embed=success_embed(f"⏱️ Compraste **{item['name']}** — {role.mention} hasta <t:{ts}:R>.")
            )

        elif item["type"] == "xp":
            await db.add_coins(interaction.guild_id, interaction.user.id, -item["price"])
            from utils.levels_engine import award_xp
            result = await award_xp(interaction.guild, interaction.user, item["xp_amount"], log=False, apply_multiplier=False)
            desc = f"⭐ Compraste **{item['name']}** — +{item['xp_amount']} XP instantánea."
            if result["leveled_up"]:
                desc += f"\n🎉 ¡Subiste a nivel **{result['new_level']}**!"
            await interaction.response.send_message(embed=success_embed(desc))

        else:  # boost
            expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=item["boost_minutes"])).isoformat()
            await db.add_coins(interaction.guild_id, interaction.user.id, -item["price"])
            await db.set_user_multiplier(interaction.guild_id, interaction.user.id, item["boost_multiplier"], expires)
            await interaction.response.send_message(
                embed=success_embed(f"⚡ Boost **x{item['boost_multiplier']}** activado durante **{item['boost_minutes']} minutos**.")
            )

    # ---------- staff ----------

    economy_group = app_commands.Group(
        name="economy",
        description="Administración de SoulCoins y la tienda (Staff)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @economy_group.command(name="additem", description="Añade un artículo a la tienda")
    @app_commands.describe(
        nombre="Nombre del artículo", precio="Precio en SoulCoins", tipo="Tipo de artículo",
        rol="Rol a otorgar (tipo=role o temprole)",
        multiplicador="Multiplicador de XP (tipo=boost)", duracion_minutos="Duración del boost en minutos (tipo=boost)",
        xp_cantidad="Cantidad de XP a otorgar (tipo=xp)",
        temprole_duracion="Duración del rol: 1h, 1d, 1w, 1mo... (tipo=temprole)",
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Rol permanente", value="role"),
        app_commands.Choice(name="Rol temporal", value="temprole"),
        app_commands.Choice(name="Boost de XP", value="boost"),
        app_commands.Choice(name="XP instantánea", value="xp"),
    ])
    async def additem(
        self, interaction: discord.Interaction, nombre: str, precio: int, tipo: app_commands.Choice[str],
        rol: Optional[discord.Role] = None, multiplicador: Optional[float] = None, duracion_minutos: Optional[int] = None,
        xp_cantidad: Optional[int] = None, temprole_duracion: Optional[str] = None,
    ):
        if tipo.value == "role" and not rol:
            await interaction.response.send_message(embed=error_embed("Para un artículo de tipo `role` debes indicar el `rol`."), ephemeral=True)
            return
        if tipo.value == "temprole":
            if not rol or not temprole_duracion:
                await interaction.response.send_message(embed=error_embed("Para `temprole` indica `rol` y `temprole_duracion`."), ephemeral=True)
                return
            from cogs.temproles import parse_duration
            parsed = parse_duration(temprole_duracion)
            if not parsed:
                await interaction.response.send_message(embed=error_embed("Duración inválida. Usa `1h`, `1d`, `1w`, `1mo` (máx. 1 año)."), ephemeral=True)
                return
            expires_iso, _ = parsed
            seconds = int((datetime.datetime.fromisoformat(expires_iso) - datetime.datetime.utcnow()).total_seconds())
        if tipo.value == "boost" and (not multiplicador or not duracion_minutos):
            await interaction.response.send_message(embed=error_embed("Para `boost` indica `multiplicador` y `duracion_minutos`."), ephemeral=True)
            return
        if tipo.value == "xp" and not xp_cantidad:
            await interaction.response.send_message(embed=error_embed("Para `xp` indica `xp_cantidad`."), ephemeral=True)
            return

        item_id = await db.add_shop_item(
            interaction.guild_id, nombre, precio, tipo.value,
            role_id=rol.id if rol else None, boost_multiplier=multiplicador, boost_minutes=duracion_minutos,
            xp_amount=xp_cantidad, temprole_seconds=seconds if tipo.value == "temprole" else None,
        )
        await interaction.response.send_message(embed=success_embed(f"Artículo **{nombre}** añadido con ID `#{item_id}`."))

    @economy_group.command(name="removeitem", description="Elimina un artículo de la tienda")
    @app_commands.describe(item_id="ID del artículo a eliminar")
    async def removeitem(self, interaction: discord.Interaction, item_id: int):
        removed = await db.remove_shop_item(interaction.guild_id, item_id)
        if removed:
            await interaction.response.send_message(embed=success_embed(f"Artículo `#{item_id}` eliminado."))
        else:
            await interaction.response.send_message(embed=error_embed("Ese artículo no existe."), ephemeral=True)

    @economy_group.command(name="addcoins", description="Añade SoulCoins a un usuario")
    @app_commands.describe(usuario="Usuario", cantidad="Cantidad a añadir")
    async def addcoins(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        new_balance = await db.add_coins(interaction.guild_id, usuario.id, cantidad)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} ahora tiene **{new_balance}** SoulCoins."))

    @economy_group.command(name="removecoins", description="Quita SoulCoins a un usuario")
    @app_commands.describe(usuario="Usuario", cantidad="Cantidad a quitar")
    async def removecoins(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        new_balance = await db.add_coins(interaction.guild_id, usuario.id, -cantidad)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} ahora tiene **{new_balance}** SoulCoins."))

    @economy_group.command(name="setcoins", description="Fija el saldo exacto de un usuario")
    @app_commands.describe(usuario="Usuario", cantidad="Saldo exacto")
    async def setcoins(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        await db.set_balance(interaction.guild_id, usuario.id, cantidad)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} ahora tiene **{cantidad}** SoulCoins."))


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))
