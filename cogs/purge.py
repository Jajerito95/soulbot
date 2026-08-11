from __future__ import annotations
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from database import get_guild_config, log_staff_action
from utils.embeds import error_embed, success_embed
from cogs.logs import log_embed


class PurgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="purge", description="Elimina mensajes de este canal (con filtros opcionales)")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(
        cantidad="Número de mensajes a revisar (máx. 200)",
        usuario="Solo eliminar mensajes de este usuario (opcional)",
        contiene="Solo eliminar mensajes que contengan este texto (opcional)",
        bots="Solo eliminar mensajes de bots (opcional)",
    )
    async def purge(
        self,
        interaction: discord.Interaction,
        cantidad: app_commands.Range[int, 1, 200],
        usuario: Optional[discord.Member] = None,
        contiene: Optional[str] = None,
        bots: Optional[bool] = None,
    ):
        def check(msg: discord.Message) -> bool:
            if usuario and msg.author.id != usuario.id:
                return False
            if contiene and contiene.lower() not in (msg.content or "").lower():
                return False
            if bots and not msg.author.bot:
                return False
            return True

        await interaction.response.defer(ephemeral=True)

        try:
            deleted = await interaction.channel.purge(limit=cantidad, check=check)
        except discord.Forbidden:
            await interaction.followup.send(embed=error_embed("No tengo permiso para eliminar mensajes en este canal."))
            return
        except discord.HTTPException as e:
            await interaction.followup.send(embed=error_embed(f"Error al eliminar mensajes: {e.text}"))
            return

        await interaction.followup.send(
            embed=success_embed(f"🧹 Se eliminaron **{len(deleted)}** mensajes en {interaction.channel.mention}.")
        )

        filtros = []
        if usuario:
            filtros.append(f"👤 Usuario: {usuario.mention}")
        if contiene:
            filtros.append(f"🔎 Contiene: `{contiene}`")
        if bots:
            filtros.append("🤖 Solo bots")

        embed = log_embed(
            "🧹 Purge ejecutado",
            f"🛡️ Staff: {interaction.user.mention}\n"
            f"📍 Canal: {interaction.channel.mention}\n"
            f"🗑️ Eliminados: **{len(deleted)}**"
            + ("\n" + "\n".join(filtros) if filtros else ""),
        )
        config = await get_guild_config(interaction.guild_id)
        if config["logs_channel_id"] and config["logs_moderation"]:
            channel = interaction.guild.get_channel(config["logs_channel_id"])
            if channel:
                await channel.send(embed=embed)

        await log_staff_action(
            interaction.guild_id, usuario.id if usuario else 0, interaction.user.id, "purge",
            f"{len(deleted)} mensajes en #{interaction.channel.name}",
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PurgeCog(bot))
