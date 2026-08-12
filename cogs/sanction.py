from __future__ import annotations
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import get_guild_config, log_staff_action, get_user_sanctions
from utils.embeds import success_embed, error_embed, base_embed
from cogs.logs import log_embed
from cogs.sanction_data import INFRACTIONS, infraction_choices, get_punishment
from utils.sanctions_engine import apply_sanction, is_imgur, requires_evidence, punishment_label
import database as db
from discord.ext import tasks
from config import COLOR_ERROR

IMGUR_RE = re.compile(r"^https?://(www\.)?(i\.)?imgur\.com/.+", re.IGNORECASE)

ACTION_ICON = {"warn": "⚠️", "ban": "🔨", "unban": "🔓"}


def is_imgur(url: str) -> bool:
    return bool(IMGUR_RE.match(url.strip()))


async def _send_log(guild: discord.Guild, title: str, description: str):
    config = await get_guild_config(guild.id)
    if config["logs_channel_id"] and config["logs_moderation"]:
        channel = guild.get_channel(config["logs_channel_id"])
        if channel:
            await channel.send(embed=log_embed(title, description, color=COLOR_ERROR))


class SanctionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_temp_bans.start()

    def cog_unload(self):
        self.check_temp_bans.cancel()

    @tasks.loop(minutes=5)
    async def check_temp_bans(self):
        for guild_id, user_id in await db.get_due_temp_bans():
            guild = self.bot.get_guild(guild_id)
            if guild:
                try:
                    await guild.unban(discord.Object(id=user_id), reason="Ban temporal expirado (automático)")
                except (discord.NotFound, discord.Forbidden):
                    pass
            await db.remove_temp_ban(guild_id, user_id)

    @check_temp_bans.before_loop
    async def before_check_temp_bans(self):
        await self.bot.wait_until_ready()

    sanction_group = app_commands.Group(
        name="sanction",
        description="Sistema de sanciones de SoulBot (Staff)",
        default_permissions=discord.Permissions(moderate_members=True),
    )

    @sanction_group.command(name="warn", description="Advierte a un usuario")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(usuario="Usuario a advertir", razon="Motivo del warn", evidencia="Link de Imgur (opcional)")
    async def sanction_warn(
        self, interaction: discord.Interaction, usuario: discord.Member, razon: str, evidencia: Optional[str] = None
    ):
        if evidencia and not is_imgur(evidencia):
            await interaction.response.send_message(
                embed=error_embed("La evidencia debe ser un link de Imgur (imgur.com)."), ephemeral=True
            )
            return

        sanction_id = await log_staff_action(interaction.guild_id, usuario.id, interaction.user.id, "warn", razon, evidencia)

        try:
            await usuario.send(
                embed=base_embed(
                    f"⚠️ Has recibido un **warn** en **{interaction.guild.name}**.\n📝 Razón: {razon}",
                    COLOR_ERROR,
                    title="⚠️ Advertencia",
                )
            )
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            embed=success_embed(f"{usuario.mention} advertido. ID de sanción: `#{sanction_id}`")
        )
        desc = f"👤 Usuario: {usuario.mention}\n🛡️ Staff: {interaction.user.mention}\n📝 Razón: {razon}\n🆔 ID: `#{sanction_id}`"
        if evidencia:
            desc += f"\n🔗 Evidencia: {evidencia}"
        await _send_log(interaction.guild, "⚠️ Warn aplicado", desc)

    @sanction_group.command(name="ban", description="Banea a un usuario (evidencia de Imgur obligatoria)")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(
        usuario="Usuario a banear", razon="Motivo del ban", evidencia="Link de Imgur (OBLIGATORIO)",
        borrar_mensajes="Días de mensajes a borrar (0-7, opcional)",
    )
    async def sanction_ban(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        razon: str,
        evidencia: str,
        borrar_mensajes: app_commands.Range[int, 0, 7] = 0,
    ):
        if not is_imgur(evidencia):
            await interaction.response.send_message(
                embed=error_embed("El ban requiere evidencia en formato Imgur (imgur.com). Sube la captura ahí primero."),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            await usuario.send(
                embed=base_embed(
                    f"🔨 Has sido **baneado** de **{interaction.guild.name}**.\n📝 Razón: {razon}",
                    COLOR_ERROR,
                    title="🔨 Ban",
                )
            )
        except discord.Forbidden:
            pass

        try:
            await interaction.guild.ban(usuario, reason=razon, delete_message_days=borrar_mensajes)
        except discord.Forbidden:
            await interaction.followup.send(embed=error_embed("No tengo permiso para banear a ese usuario."))
            return

        sanction_id = await log_staff_action(interaction.guild_id, usuario.id, interaction.user.id, "ban", razon, evidencia)

        await interaction.followup.send(
            embed=success_embed(f"{usuario.mention} baneado. ID de sanción: `#{sanction_id}`")
        )
        await _send_log(
            interaction.guild,
            "🔨 Ban aplicado",
            f"👤 Usuario: {usuario.mention} (`{usuario.id}`)\n🛡️ Staff: {interaction.user.mention}\n"
            f"📝 Razón: {razon}\n🆔 ID: `#{sanction_id}`\n🔗 Evidencia: {evidencia}",
        )

    @sanction_group.command(name="unban", description="Desbanea a un usuario por su ID")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.describe(usuario_id="ID del usuario baneado", razon="Motivo del unban")
    async def sanction_unban(self, interaction: discord.Interaction, usuario_id: str, razon: str):
        if not usuario_id.isdigit():
            await interaction.response.send_message(embed=error_embed("El ID debe ser numérico."), ephemeral=True)
            return

        user = discord.Object(id=int(usuario_id))
        try:
            await interaction.guild.unban(user, reason=razon)
        except discord.NotFound:
            await interaction.response.send_message(embed=error_embed("Ese usuario no está baneado."), ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("No tengo permiso para desbanear."), ephemeral=True
            )
            return

        sanction_id = await log_staff_action(interaction.guild_id, int(usuario_id), interaction.user.id, "unban", razon)

        await interaction.response.send_message(
            embed=success_embed(f"Usuario `{usuario_id}` desbaneado. ID de sanción: `#{sanction_id}`")
        )
        await _send_log(
            interaction.guild,
            "🔓 Unban aplicado",
            f"👤 Usuario: `{usuario_id}`\n🛡️ Staff: {interaction.user.mention}\n📝 Razón: {razon}\n🆔 ID: `#{sanction_id}`",
        )

    @sanction_group.command(name="auto", description="Aplica la sanción correcta automáticamente según el catálogo e historial")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(usuario="Usuario a sancionar", infraccion="Tipo de infracción", razon="Detalle del caso", evidencia="Link de Imgur")
    async def sanction_auto(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        infraccion: str,
        razon: str,
        evidencia: Optional[str] = None,
    ):
        if infraccion not in INFRACTIONS:
            await interaction.response.send_message(embed=error_embed("Infracción no reconocida. Selecciónala de la lista."), ephemeral=True)
            return

        previous_count = await db.get_infraction_count(interaction.guild_id, usuario.id, infraccion)
        punishment = get_punishment(infraccion, previous_count)

        if requires_evidence(punishment) and not evidencia:
            await interaction.response.send_message(
                embed=error_embed(
                    f"Esta infracción corresponde a **{punishment_label(punishment)}** (sanción grande). "
                    "La evidencia en Imgur es obligatoria."
                ),
                ephemeral=True,
            )
            return
        if evidencia and not is_imgur(evidencia):
            await interaction.response.send_message(embed=error_embed("La evidencia debe ser un link de Imgur (imgur.com)."), ephemeral=True)
            return

        await interaction.response.defer()
        try:
            result = await apply_sanction(interaction.guild, usuario, infraccion, interaction.user.id, razon, evidencia)
        except discord.Forbidden:
            await interaction.followup.send(embed=error_embed("No tengo permisos suficientes para sancionar a ese usuario."))
            return

        await interaction.followup.send(
            embed=success_embed(
                f"{usuario.mention} sancionado: **{punishment_label(result['punishment'])}**\n"
                f"ID de sanción: `#{result['sanction_id']}` • Reincidencia #{result['count']}"
            )
        )

    @sanction_auto.autocomplete("infraccion")
    async def infraccion_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()
        matches = [c for c in infraction_choices() if current in c[1].lower()]
        return [app_commands.Choice(name=label, value=key) for key, label in matches[:25]]

    @sanction_group.command(name="info", description="Muestra el historial de sanciones de un usuario")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(usuario="Usuario a consultar")
    async def sanction_info(self, interaction: discord.Interaction, usuario: discord.User):
        sanciones = await get_user_sanctions(interaction.guild_id, usuario.id)

        if not sanciones:
            await interaction.response.send_message(
                embed=success_embed(f"{usuario.mention} no tiene sanciones registradas.", title="📋 Historial limpio")
            )
            return

        lines = []
        for s in sanciones[:10]:
            icon = ACTION_ICON.get(s["action"], "•")
            line = f"{icon} `#{s['id']}` **{s['action'].upper()}** — <@{s['staff_id']}>\n📝 {s['reason'] or 'Sin razón'}"
            if s["evidence_url"]:
                line += f" • [Evidencia]({s['evidence_url']})"
            lines.append(line)

        embed = base_embed(
            "\n\n".join(lines),
            COLOR_ERROR,
            title=f"📋 Historial de {usuario.display_name} ({len(sanciones)} total)",
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SanctionCog(bot))
