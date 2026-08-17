from __future__ import annotations
import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

MAX_DAYS = 90  # 3 meses


MAX_SECONDS = 365 * 24 * 3600  # 1 año


def parse_duration(text: str) -> Optional[tuple[str, str]]:
    """
    Convierte '30s', '10m', '2h', '7d', '2w', '1mo', '1y' en (timestamp ISO futuro, texto legible).
    None si el formato es inválido o supera 1 año.
    Unidades: s=segundo, m=minuto, h=hora, d=día, w=semana, mo=mes(30d), y=año(365d)
    """
    text = text.strip().lower()
    if text.endswith("mo"):
        unit, amount_str = "mo", text[:-2]
    else:
        unit, amount_str = text[-1], text[:-1]

    try:
        amount = int(amount_str)
    except ValueError:
        return None
    if amount <= 0:
        return None

    seconds_map = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "mo": 2592000, "y": 31536000}
    if unit not in seconds_map:
        return None

    total_seconds = amount * seconds_map[unit]
    if total_seconds > MAX_SECONDS:
        return None

    unit_names = {"s": "segundo(s)", "m": "minuto(s)", "h": "hora(s)", "d": "día(s)", "w": "semana(s)", "mo": "mes(es)", "y": "año(s)"}
    human = f"{amount} {unit_names[unit]}"

    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(seconds=total_seconds)).isoformat()
    return expires_at, human


class TempRolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_temp_roles.start()

    def cog_unload(self):
        self.check_temp_roles.cancel()

    @tasks.loop(minutes=5)
    async def check_temp_roles(self):
        for guild_id, user_id, role_id in await db.get_due_temp_roles():
            guild = self.bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(user_id)
                role = guild.get_role(role_id)
                if member and role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Rol temporal expirado (automático)")
                    except discord.Forbidden:
                        pass
            await db.remove_temp_role_record(guild_id, user_id, role_id)

    @check_temp_roles.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    role_group = app_commands.Group(
        name="role",
        description="Gestión de roles temporales (Staff)",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @role_group.command(name="temp", description="Asigna un rol temporal (máx. 1 año)")
    @app_commands.describe(
        usuario="Usuario que recibe el rol",
        rol="Rol a asignar",
        duracion="Duración: 30s, 10m, 2h, 7d, 2w, 1mo, 1y (máx. 1 año)",
    )
    async def temp(self, interaction: discord.Interaction, usuario: discord.Member, rol: discord.Role, duracion: str):
        parsed = parse_duration(duracion)
        if not parsed:
            await interaction.response.send_message(
                embed=error_embed("Duración inválida. Usa `30s`, `10m`, `2h`, `7d`, `2w`, `1mo` o `1y` (máximo 1 año)."),
                ephemeral=True,
            )
            return
        expires_at, human = parsed

        if rol >= interaction.guild.me.top_role:
            await interaction.response.send_message(embed=error_embed("No puedo asignar un rol igual o superior al mío."), ephemeral=True)
            return

        try:
            await usuario.add_roles(rol, reason=f"Rol temporal por {human} (asignado por {interaction.user})")
        except discord.Forbidden:
            await interaction.response.send_message(embed=error_embed("No tengo permiso para asignar ese rol."), ephemeral=True)
            return

        await db.add_temp_role(interaction.guild_id, usuario.id, rol.id, expires_at, interaction.user.id)

        expire_ts = int(datetime.datetime.fromisoformat(expires_at).timestamp())
        await interaction.response.send_message(
            embed=success_embed(f"{rol.mention} asignado a {usuario.mention}.\n⏱️ Expira: <t:{expire_ts}:F> (<t:{expire_ts}:R>)")
        )

    @role_group.command(name="list", description="Muestra los roles temporales activos de un usuario")
    @app_commands.describe(usuario="Usuario a consultar")
    async def list_roles(self, interaction: discord.Interaction, usuario: discord.Member):
        roles = await db.get_active_temp_roles(interaction.guild_id, usuario.id)
        if not roles:
            await interaction.response.send_message(embed=error_embed(f"{usuario.mention} no tiene roles temporales activos."))
            return

        lines = []
        for role_id, expires_at in roles:
            ts = int(datetime.datetime.fromisoformat(expires_at).timestamp())
            lines.append(f"🎭 <@&{role_id}> — expira <t:{ts}:R>")

        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title=f"⏱️ Roles temporales de {usuario.display_name}"))

    @role_group.command(name="remove", description="Quita un rol temporal antes de tiempo")
    @app_commands.describe(usuario="Usuario", rol="Rol a quitar")
    async def remove(self, interaction: discord.Interaction, usuario: discord.Member, rol: discord.Role):
        try:
            await usuario.remove_roles(rol, reason=f"Rol temporal removido manualmente por {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(embed=error_embed("No tengo permiso para quitar ese rol."), ephemeral=True)
            return

        await db.remove_temp_role_record(interaction.guild_id, usuario.id, rol.id)
        await interaction.response.send_message(embed=success_embed(f"{rol.mention} removido de {usuario.mention} antes de tiempo."))


async def setup(bot: commands.Bot):
    await bot.add_cog(TempRolesCog(bot))
