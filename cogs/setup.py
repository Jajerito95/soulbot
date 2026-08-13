from __future__ import annotations
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from database import update_guild_config, get_guild_config
from utils.embeds import success_embed, error_embed
from cogs.tickets import build_panel_embed, TicketPanelView, load_categories


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

    @setup_group.command(name="tickets", description="Configura el sistema de Tickets")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        categoria="Categoría de Discord donde se crean los tickets",
        staff_role="Rol que puede ver y gestionar los tickets",
        canal_panel="Canal donde se enviará el panel de apertura",
        canal_logs="Canal donde se registran los tickets cerrados (con transcript)",
        categorias="Lista de categorías separadas por coma (ej: Soporte,Reportes,Apelaciones)",
        max_activos="Máximo de tickets abiertos a la vez antes de poner en cola",
        pausado="Pausa manualmente la apertura de nuevos tickets (van a cola)",
        enviar_panel="Envía/actualiza el panel en el canal configurado",
    )
    async def setup_tickets(
        self,
        interaction: discord.Interaction,
        categoria: Optional[discord.CategoryChannel] = None,
        staff_role: Optional[discord.Role] = None,
        canal_panel: Optional[discord.TextChannel] = None,
        canal_logs: Optional[discord.TextChannel] = None,
        categorias: Optional[str] = None,
        max_activos: Optional[int] = None,
        pausado: Optional[bool] = None,
        enviar_panel: Optional[bool] = None,
    ):
        fields = {}
        if categoria is not None:
            fields["tickets_category_id"] = categoria.id
        if staff_role is not None:
            fields["tickets_staff_role_id"] = staff_role.id
        if canal_panel is not None:
            fields["tickets_panel_channel_id"] = canal_panel.id
        if canal_logs is not None:
            fields["tickets_log_channel_id"] = canal_logs.id
        if categorias is not None:
            import json
            parsed = [[name.strip(), "🎫"] for name in categorias.split(",") if name.strip()]
            fields["tickets_categories"] = json.dumps(parsed, ensure_ascii=False)
        if max_activos is not None:
            fields["tickets_max_active"] = max_activos
        if pausado is not None:
            fields["tickets_paused"] = int(pausado)

        if fields:
            await update_guild_config(interaction.guild_id, **fields)

        config = await get_guild_config(interaction.guild_id)

        if enviar_panel:
            target = canal_panel or (interaction.guild.get_channel(config["tickets_panel_channel_id"]) if config["tickets_panel_channel_id"] else None)
            if not target:
                await interaction.response.send_message(
                    embed=error_embed("Configura primero `canal_panel` antes de enviar el panel."), ephemeral=True
                )
                return
            view = TicketPanelView(load_categories(config))
            self.bot.add_view(view)
            await target.send(embed=build_panel_embed(), view=view)

        categoria_txt = f"<#{config['tickets_category_id']}>" if config["tickets_category_id"] else "No configurada"
        staff_txt = f"<@&{config['tickets_staff_role_id']}>" if config["tickets_staff_role_id"] else "No configurado"
        panel_txt = f"<#{config['tickets_panel_channel_id']}>" if config["tickets_panel_channel_id"] else "No configurado"
        logs_txt = f"<#{config['tickets_log_channel_id']}>" if config["tickets_log_channel_id"] else "No configurado"
        pausado_txt = "⏸️ Sí" if config["tickets_paused"] else "▶️ No"

        await interaction.response.send_message(
            embed=success_embed(
                f"📂 Categoría: {categoria_txt}\n🛡️ Rol Staff: {staff_txt}\n📌 Canal panel: {panel_txt}\n"
                f"📜 Canal logs: {logs_txt}\n🔢 Máx. activos: **{config['tickets_max_active']}**\n⏸️ Pausado: {pausado_txt}",
                title="🎫 Configuración de Tickets",
            ),
            ephemeral=True,
        )

    @setup_group.command(name="levels", description="Configura el canal de anuncios de subida de nivel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(canal="Canal donde se anuncian las subidas de nivel (vacío = mismo canal del mensaje)")
    async def setup_levels(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
        if canal is not None:
            await update_guild_config(interaction.guild_id, levels_announce_channel_id=canal.id)
        config = await get_guild_config(interaction.guild_id)
        canal_txt = f"<#{config['levels_announce_channel_id']}>" if config["levels_announce_channel_id"] else "Mismo canal del mensaje"
        await interaction.response.send_message(embed=success_embed(f"📢 Canal de anuncios de nivel: {canal_txt}"), ephemeral=True)

    @setup_group.command(name="appeals", description="Configura el canal de revisión de apelaciones")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(canal="Canal donde se publican las apelaciones para revisar")
    async def setup_appeals(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
        if canal is not None:
            await update_guild_config(interaction.guild_id, appeals_channel_id=canal.id)
        config = await get_guild_config(interaction.guild_id)
        canal_txt = f"<#{config['appeals_channel_id']}>" if config["appeals_channel_id"] else "No configurado"
        await interaction.response.send_message(embed=success_embed(f"📮 Canal de apelaciones: {canal_txt}"), ephemeral=True)

    @setup_group.command(name="automod", description="Activa o desactiva el AutoMod (spam, flood, mayúsculas, ghost ping, publicidad)")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(activo="Activar o desactivar el AutoMod")
    async def setup_automod(self, interaction: discord.Interaction, activo: Optional[bool] = None):
        if activo is not None:
            await update_guild_config(interaction.guild_id, automod_enabled=int(activo))

        config = await get_guild_config(interaction.guild_id)
        estado = "✅ Activado" if config["automod_enabled"] else "❌ Desactivado"
        await interaction.response.send_message(
            embed=success_embed(
                f"Estado: {estado}\n\n"
                "Detecta automáticamente: Spam, Flood, Mayúsculas excesivas, Ghost Ping y Publicidad (invites), "
                "aplicando la sanción del catálogo según reincidencia.\n"
                "⚠️ El Staff (permiso `moderate_members`) está exento.",
                title="🤖 AutoMod",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
