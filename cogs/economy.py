from __future__ import annotations
import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

DAILY_MIN, DAILY_MAX = 100, 250
DAILY_COOLDOWN_HOURS = 24


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- comandos de miembro ----------

    @app_commands.command(name="balance", description="Muestra tus SoulCoins o los de otro usuario")
    @app_commands.describe(usuario="Usuario a consultar (opcional)")
    async def balance(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        target = usuario or interaction.user
        coins = await db.get_balance(interaction.guild_id, target.id)
        embed = base_embed(f"💰 **{coins}** SoulCoins", COLOR, title=f"👛 Cartera de {target.display_name}")
        embed.set_thumbnail(url=target.display_avatar.url)
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
        amount = random.randint(DAILY_MIN, DAILY_MAX)
        new_balance = await db.add_coins(interaction.guild_id, interaction.user.id, amount)
        await db.set_last_daily(interaction.guild_id, interaction.user.id, now.isoformat())

        await interaction.response.send_message(
            embed=success_embed(f"💰 Has recibido **{amount}** SoulCoins.\n👛 Saldo actual: **{new_balance}**", title="🎁 Daily reclamado")
        )

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

        lines = []
        for item in items:
            if item["type"] == "role":
                detail = f"🎭 Rol <@&{item['role_id']}>"
            else:
                detail = f"⚡ Boost x{item['boost_multiplier']} por {item['boost_minutes']} min"
            lines.append(f"`#{item['id']}` **{item['name']}** — 💰 {item['price']}\n{detail}")

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
        nombre="Nombre del artículo", precio="Precio en SoulCoins", tipo="role o boost",
        rol="Rol a otorgar (si tipo=role)", multiplicador="Multiplicador de XP (si tipo=boost)",
        duracion_minutos="Duración del boost en minutos (si tipo=boost)",
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Rol", value="role"),
        app_commands.Choice(name="Boost de XP", value="boost"),
    ])
    async def additem(
        self, interaction: discord.Interaction, nombre: str, precio: int, tipo: app_commands.Choice[str],
        rol: Optional[discord.Role] = None, multiplicador: Optional[float] = None, duracion_minutos: Optional[int] = None,
    ):
        if tipo.value == "role" and not rol:
            await interaction.response.send_message(embed=error_embed("Para un artículo de tipo `role` debes indicar el `rol`."), ephemeral=True)
            return
        if tipo.value == "boost" and (not multiplicador or not duracion_minutos):
            await interaction.response.send_message(embed=error_embed("Para un artículo de tipo `boost` indica `multiplicador` y `duracion_minutos`."), ephemeral=True)
            return

        item_id = await db.add_shop_item(
            interaction.guild_id, nombre, precio, tipo.value,
            role_id=rol.id if rol else None, boost_multiplier=multiplicador, boost_minutes=duracion_minutos,
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
