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

    @sanction_group.command(name="autoremove", description="Anula una sanción aplicada por error (revierte la reincidencia y desbanea si aplica)")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(sancion_id="ID de la sanción a anular")
    async def sanction_autoremove(self, interaction: discord.Interaction, sancion_id: int):
        sanction = await db.get_sanction_by_id(interaction.guild_id, sancion_id)
        if not sanction:
            await interaction.response.send_message(embed=error_embed("No existe ninguna sanción con ese ID."), ephemeral=True)
            return

        await interaction.response.defer()

        if sanction["infraction_key"]:
            await db.decrement_infraction_count(interaction.guild_id, sanction["target_id"], sanction["infraction_key"])

        if sanction["action"] == "ban":
            try:
                await interaction.guild.unban(discord.Object(id=sanction["target_id"]), reason=f"Sanción #{sancion_id} anulada por {interaction.user}")
            except (discord.NotFound, discord.Forbidden):
                pass
            await db.remove_temp_ban(interaction.guild_id, sanction["target_id"])

        await db.delete_staff_action(sancion_id)

        await interaction.followup.send(
            embed=success_embed(f"Sanción `#{sancion_id}` anulada. Se revirtió la reincidencia" + (" y se desbaneó al usuario." if sanction["action"] == "ban" else "."))
        )
        await _send_log(
            interaction.guild, "🗑️ Sanción anulada",
            f"🆔 ID: `#{sancion_id}`\n👤 Usuario: <@{sanction['target_id']}>\n🛡️ Anulada por: {interaction.user.mention}",
        )

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
