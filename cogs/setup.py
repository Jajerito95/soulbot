from __future__ import annotations
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from database import update_guild_config, get_guild_config
from utils.embeds import success_embed


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    setup_group = app_commands.Group(
        name="setup",
        description="Configuración de SoulBot (Staff)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @setup_group.command(name="invites", description="Configura el sistema de bienvenida e invitaciones")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        canal_bienvenida="Canal donde se enviarán los mensajes de bienvenida",
        mensaje="Mensaje de bienvenida (usa {mention}, {user}, {member_count})",
        activo="Activar o desactivar el sistema",
    )
    async def setup_invites(
        self,
        interaction: discord.Interaction,
        canal_bienvenida: Optional[discord.TextChannel] = None,
        mensaje: Optional[str] = None,
        activo: Optional[bool] = None,
    ):
        fields = {}
        if canal_bienvenida is not None:
            fields["welcome_channel_id"] = canal_bienvenida.id
        if mensaje is not None:
            fields["welcome_message"] = mensaje
        if activo is not None:
            fields["welcome_enabled"] = int(activo)

        if fields:
            await update_guild_config(interaction.guild_id, **fields)

        config = await get_guild_config(interaction.guild_id)
        canal = f"<#{config['welcome_channel_id']}>" if config["welcome_channel_id"] else "No configurado"
        estado = "✅ Activado" if config["welcome_enabled"] else "❌ Desactivado"

        await interaction.response.send_message(
            embed=success_embed(f"📢 Canal: {canal}\n⚙️ Estado: {estado}", title="👋 Configuración de bienvenida"),
            ephemeral=True,
        )

    @setup_group.command(name="suggestion", description="Configura el sistema de sugerencias")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        canal="Canal donde se podrán enviar sugerencias",
        votos_aprobar="Votos 🟢 necesarios para auto-aprobar (0 = desactivado)",
        votos_denegar="Votos 🔴 necesarios para auto-denegar (0 = desactivado)",
    )
    async def setup_suggestion(
        self,
        interaction: discord.Interaction,
        canal: Optional[discord.TextChannel] = None,
        votos_aprobar: Optional[int] = None,
        votos_denegar: Optional[int] = None,
    ):
        fields = {}
        if canal is not None:
            fields["suggestion_channel_id"] = canal.id
        if votos_aprobar is not None:
            fields["auto_approve_votes"] = votos_aprobar
        if votos_denegar is not None:
            fields["auto_deny_votes"] = votos_denegar

        if fields:
            await update_guild_config(interaction.guild_id, **fields)

        config = await get_guild_config(interaction.guild_id)
        canal_txt = f"<#{config['suggestion_channel_id']}>" if config["suggestion_channel_id"] else "No configurado"

        await interaction.response.send_message(
            embed=success_embed(
                f"💡 Canal permitido: {canal_txt}\n"
                f"⚙️ Auto-aprobación: **{config['auto_approve_votes']} 🟢**\n"
                f"⚙️ Auto-denegación: **{config['auto_deny_votes']} 🔴**",
                title="🗳️ Configuración de sugerencias",
            ),
            ephemeral=True,
        )

    @setup_group.command(name="logs", description="Configura el sistema de logs del servidor")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        canal="Canal donde se enviarán los logs",
        miembros="Registrar entradas/salidas de miembros",
        moderacion="Registrar baneos, expulsiones y timeouts",
        mensajes="Registrar mensajes eliminados/editados",
        roles="Registrar cambios de roles",
        canales="Registrar cambios de canales",
    )
    async def setup_logs(
        self,
        interaction: discord.Interaction,
        canal: Optional[discord.TextChannel] = None,
        miembros: Optional[bool] = None,
        moderacion: Optional[bool] = None,
        mensajes: Optional[bool] = None,
        roles: Optional[bool] = None,
        canales: Optional[bool] = None,
    ):
        fields = {}
        if canal is not None:
            fields["logs_channel_id"] = canal.id
        if miembros is not None:
            fields["logs_members"] = int(miembros)
        if moderacion is not None:
            fields["logs_moderation"] = int(moderacion)
        if mensajes is not None:
            fields["logs_messages"] = int(mensajes)
        if roles is not None:
            fields["logs_roles"] = int(roles)
        if canales is not None:
            fields["logs_channels"] = int(canales)

        if fields:
            await update_guild_config(interaction.guild_id, **fields)

        config = await get_guild_config(interaction.guild_id)
        canal_txt = f"<#{config['logs_channel_id']}>" if config["logs_channel_id"] else "No configurado"

        def flag(v):
            return "✅" if v else "❌"

        await interaction.response.send_message(
            embed=success_embed(
                f"📜 Canal: {canal_txt}\n"
                f"👤 Miembros: {flag(config['logs_members'])}\n"
                f"🛡️ Moderación: {flag(config['logs_moderation'])}\n"
                f"💬 Mensajes: {flag(config['logs_messages'])}\n"
                f"🎭 Roles: {flag(config['logs_roles'])}\n"
                f"📁 Canales: {flag(config['logs_channels'])}",
                title="📜 Configuración de logs",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
