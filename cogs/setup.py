from __future__ import annotations
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from database import update_guild_config, get_guild_config
from utils.embeds import success_embed, error_embed
from cogs.tickets import build_panel_embed, build_panel_banner, TicketPanelView, load_categories


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
            banner_file = await build_panel_banner(interaction.guild)
            await target.send(embed=build_panel_embed(), view=view, file=banner_file)

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

    @setup_group.command(name="rates", description="Ajusta el XP, daily y recompensas de juegos del servidor")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        xp_mensaje_min="XP mínima por mensaje", xp_mensaje_max="XP máxima por mensaje",
        xp_mensaje_cooldown="Segundos de cooldown entre mensajes que dan XP",
        xp_voz_minuto="XP por minuto en canal de voz",
        daily_min="SoulCoins mínimas del /daily", daily_max="SoulCoins máximas del /daily",
        coins_por_nivel="Multiplicador de SoulCoins al subir de nivel (nivel × esto)",
        juego_gana="SoulCoins al ganar un juego de mesa", juego_empate="SoulCoins en empate",
        trivia_recompensa="SoulCoins al acertar la trivia",
    )
    async def setup_rates(
        self, interaction: discord.Interaction,
        xp_mensaje_min: Optional[int] = None, xp_mensaje_max: Optional[int] = None, xp_mensaje_cooldown: Optional[int] = None,
        xp_voz_minuto: Optional[int] = None, daily_min: Optional[int] = None, daily_max: Optional[int] = None,
        coins_por_nivel: Optional[int] = None, juego_gana: Optional[int] = None, juego_empate: Optional[int] = None,
        trivia_recompensa: Optional[int] = None,
    ):
        fields = {}
        if xp_mensaje_min is not None:
            fields["message_xp_min"] = xp_mensaje_min
        if xp_mensaje_max is not None:
            fields["message_xp_max"] = xp_mensaje_max
        if xp_mensaje_cooldown is not None:
            fields["message_xp_cooldown"] = xp_mensaje_cooldown
        if xp_voz_minuto is not None:
            fields["voice_xp_per_minute"] = xp_voz_minuto
        if daily_min is not None:
            fields["daily_min"] = daily_min
        if daily_max is not None:
            fields["daily_max"] = daily_max
        if coins_por_nivel is not None:
            fields["levelup_coin_multiplier"] = coins_por_nivel
        if juego_gana is not None:
            fields["game_win_reward"] = juego_gana
        if juego_empate is not None:
            fields["game_draw_reward"] = juego_empate
        if trivia_recompensa is not None:
            fields["trivia_reward"] = trivia_recompensa

        if fields:
            await update_guild_config(interaction.guild_id, **fields)

        config = await get_guild_config(interaction.guild_id)
        await interaction.response.send_message(
            embed=success_embed(
                f"💬 XP mensaje: **{config['message_xp_min']}-{config['message_xp_max']}** cada **{config['message_xp_cooldown']}s**\n"
                f"🎙️ XP voz: **{config['voice_xp_per_minute']}**/min\n"
                f"🎁 Daily: **{config['daily_min']}-{config['daily_max']}** SoulCoins\n"
                f"⭐ Coins por nivel: **nivel × {config['levelup_coin_multiplier']}**\n"
                f"🎲 Juegos: gana **{config['game_win_reward']}** / empate **{config['game_draw_reward']}**\n"
                f"🧠 Trivia: **{config['trivia_reward']}**",
                title="⚙️ Tasas de XP y economía",
            ),
            ephemeral=True,
        )

    @setup_group.command(name="automod", description="Configura el AutoMod: activar/desactivar general, por función, y el umbral de avisos")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        activo="Interruptor general del AutoMod",
        spam="Detectar mensajes repetidos",
        flood="Detectar ráfagas de mensajes",
        mayusculas="Detectar uso excesivo de mayúsculas",
        ghost_ping="Detectar menciones borradas rápido",
        publicidad="Detectar enlaces de invitación",
        avisos_antes_de_sancionar="Cuántos avisos por DM antes de aplicar la sanción real (por defecto 2)",
    )
    async def setup_automod(
        self, interaction: discord.Interaction,
        activo: Optional[bool] = None, spam: Optional[bool] = None, flood: Optional[bool] = None,
        mayusculas: Optional[bool] = None, ghost_ping: Optional[bool] = None, publicidad: Optional[bool] = None,
        avisos_antes_de_sancionar: Optional[int] = None,
    ):
        fields = {}
        if activo is not None:
            fields["automod_enabled"] = int(activo)
        if spam is not None:
            fields["automod_spam"] = int(spam)
        if flood is not None:
            fields["automod_flood"] = int(flood)
        if mayusculas is not None:
            fields["automod_caps"] = int(mayusculas)
        if ghost_ping is not None:
            fields["automod_ghostping"] = int(ghost_ping)
        if publicidad is not None:
            fields["automod_ads"] = int(publicidad)
        if avisos_antes_de_sancionar is not None:
            fields["automod_warn_threshold"] = max(0, avisos_antes_de_sancionar)

        if fields:
            await update_guild_config(interaction.guild_id, **fields)

        config = await get_guild_config(interaction.guild_id)

        def flag(v):
            return "✅" if v else "❌"

        await interaction.response.send_message(
            embed=success_embed(
                f"🔌 General: {flag(config['automod_enabled'])}\n"
                f"💬 Spam: {flag(config['automod_spam'])}\n"
                f"🌊 Flood: {flag(config['automod_flood'])}\n"
                f"🔠 Mayúsculas: {flag(config['automod_caps'])}\n"
                f"👻 Ghost Ping: {flag(config['automod_ghostping'])}\n"
                f"📢 Publicidad: {flag(config['automod_ads'])}\n"
                f"⚠️ Avisos antes de sancionar: **{config['automod_warn_threshold']}**\n\n"
                "El Staff (permiso `moderate_members`) siempre está exento.",
                title="🤖 AutoMod",
            ),
            ephemeral=True,
        )

    @setup_group.command(name="test", description="Ejecuta una batería de pruebas de todos los sistemas configurados")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(canal="Canal donde se enviará el reporte de pruebas")
    async def setup_test(self, interaction: discord.Interaction, canal: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        results = []

        def ok(label): results.append(f"✅ {label}")
        def fail(label, detail=""): results.append(f"❌ {label}" + (f" — {detail}" if detail else ""))
        def warn(label, detail=""): results.append(f"⚠️ {label}" + (f" — {detail}" if detail else ""))

        # --- Permisos en el canal de destino ---
        perms = canal.permissions_for(interaction.guild.me)
        if perms.send_messages and perms.embed_links and perms.attach_files:
            ok("Permisos del bot en el canal de test")
        else:
            fail("Permisos del bot en el canal de test", "faltan send_messages/embed_links/attach_files")

        # --- Base de datos ---
        try:
            test_cfg = await get_guild_config(interaction.guild_id)
            db_mode = "Turso (nube, persistente)" if __import__("database").USING_TURSO else "SQLite local (⚠️ no persiste en Render Free)"
            ok(f"Base de datos accesible — {db_mode}")
        except Exception as e:
            fail("Base de datos accesible", str(e))

        # --- Canales configurados ---
        channel_checks = [
            ("welcome_channel_id", "Canal de bienvenida"),
            ("suggestion_channel_id", "Canal de sugerencias"),
            ("logs_channel_id", "Canal de logs"),
            ("tickets_panel_channel_id", "Canal del panel de tickets"),
            ("tickets_log_channel_id", "Canal de logs de tickets"),
            ("appeals_channel_id", "Canal de apelaciones"),
            ("levels_announce_channel_id", "Canal de anuncios de nivel"),
        ]
        for key, label in channel_checks:
            cid = test_cfg.get(key)
            if not cid:
                warn(label, "no configurado")
                continue
            ch = interaction.guild.get_channel(cid)
            ok(label) if ch else fail(label, f"el canal `{cid}` ya no existe")

        # --- Rol de Staff de tickets ---
        if test_cfg.get("tickets_staff_role_id"):
            role = interaction.guild.get_role(test_cfg["tickets_staff_role_id"])
            ok("Rol de Staff de tickets") if role else fail("Rol de Staff de tickets", "el rol ya no existe")

        # --- Categoría de tickets ---
        if test_cfg.get("tickets_category_id"):
            cat = interaction.guild.get_channel(test_cfg["tickets_category_id"])
            ok("Categoría de tickets") if isinstance(cat, discord.CategoryChannel) else fail("Categoría de tickets", "no es una categoría válida")

        # --- AutoMod ---
        if test_cfg.get("automod_enabled"):
            activos = [n for n, c in [("spam", "automod_spam"), ("flood", "automod_flood"), ("mayúsculas", "automod_caps"), ("ghost ping", "automod_ghostping"), ("publicidad", "automod_ads")] if test_cfg.get(c)]
            ok(f"AutoMod activo ({', '.join(activos) if activos else 'sin funciones activas'})")
        else:
            warn("AutoMod", "desactivado")

        # --- Sistema de niveles ---
        ok("Sistema de niveles activo") if test_cfg.get("levels_enabled") else warn("Sistema de niveles", "pausado")

        # --- Render de /card (imagen real) ---
        try:
            from utils.card_renderer import render_card
            from utils.levels_engine import level_from_xp
            level, xp_in, xp_needed = level_from_xp(500)
            buffer = await render_card(interaction.user.name, interaction.user.display_avatar.url, level, xp_in, xp_needed, 1)
            await canal.send(content="🧪 Test de `/card`:", file=discord.File(buffer, filename="test_card.png"))
            ok("Renderizado de /card")
        except Exception as e:
            fail("Renderizado de /card", str(e))

        # --- Render de /leaderboard (imagen real) ---
        try:
            from utils.card_renderer import render_leaderboard
            entries = [{"username": interaction.user.name, "avatar_url": interaction.user.display_avatar.url, "stat_text": "Nivel 5 • 500 XP", "ratio": 0.5}]
            guild_icon = interaction.guild.icon.url if interaction.guild.icon else None
            buffer = await render_leaderboard(interaction.guild.name, guild_icon, entries, "Test")
            await canal.send(content="🧪 Test de `/leaderboard`:", file=discord.File(buffer, filename="test_lb.png"))
            ok("Renderizado de /leaderboard")
        except Exception as e:
            fail("Renderizado de /leaderboard", str(e))

        # --- Transcript de tickets ---
        try:
            from utils.transcripts import generate_transcript
            path = await generate_transcript(canal)
            ok("Generación de transcripts")
        except Exception as e:
            fail("Generación de transcripts", str(e))

        # --- Emojis custom ---
        from utils.emojis import FALLBACKS
        custom_found = [n for n in FALLBACKS if discord.utils.get(interaction.guild.emojis, name=n)]
        if custom_found:
            ok(f"Emojis custom detectados ({len(custom_found)}/{len(FALLBACKS)}): {', '.join(custom_found[:10])}" + ("..." if len(custom_found) > 10 else ""))
        else:
            warn("Emojis custom", "ninguno subido todavía, usando Unicode de respaldo")

        # --- Resumen final ---
        passed = sum(1 for r in results if r.startswith("✅"))
        warned = sum(1 for r in results if r.startswith("⚠️"))
        failed = sum(1 for r in results if r.startswith("❌"))

        chunks = ["\n".join(results[i:i + 15]) for i in range(0, len(results), 15)]
        for i, chunk in enumerate(chunks):
            embed = success_embed(chunk, title=f"🧪 Test de sistemas ({i+1}/{len(chunks)})")
            await canal.send(embed=embed)

        await canal.send(embed=success_embed(f"✅ {passed} OK · ⚠️ {warned} avisos · ❌ {failed} fallos", title="🧪 Resumen del test"))
        await interaction.followup.send(embed=success_embed(f"Test completado en {canal.mention} — {passed} OK, {warned} avisos, {failed} fallos."), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
