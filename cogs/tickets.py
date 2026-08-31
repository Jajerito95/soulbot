from __future__ import annotations
import json
import asyncio
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from utils.embeds import success_embed, error_embed, base_embed, get_footer_icon
from utils.transcripts import generate_transcript
from config import COLOR, COLOR_ERROR, PUBLIC_URL

_ticket_cooldown: dict[int, float] = {}
_FCREATE_COOLDOWN: dict[int, float] = {}


def parse_emoji(emoji_str: str):
    try:
        return discord.PartialEmoji.from_str(emoji_str)
    except Exception:
        return None


def load_categories(config: dict) -> list[tuple[str, str]]:
    try:
        return [tuple(x) for x in json.loads(config["tickets_categories"])]
    except Exception:
        return [("Soporte", "🎫")]


def build_panel_embed() -> discord.Embed:
    embed = discord.Embed(color=COLOR)
    embed.set_image(url="attachment://ticket_banner.png")
    embed.description = (
        "Abre un ticket en la categoría correspondiente y sé paciente. "
        "La impaciencia o abrir tickets innecesarios resultará en sanciones."
    )
    embed.add_field(
        name="🔔 Reglas rápidas",
        value=(
            "🕐 Ten paciencia — espera tu turno\n"
            "🤝 Respeta al Staff\n"
            "💬 Mantente activo o se cerrará por inactividad\n"
            "📂 Elige bien la categoría\n"
            "🚫 Sin motivo válido = sancionable"
        ),
        inline=False,
    )
    embed.set_footer(text="SoulSeeker™ | All rights reserved.", icon_url=get_footer_icon())
    return embed


async def build_panel_banner(guild: discord.Guild) -> discord.File:
    from utils.card_renderer import render_banner
    guild_icon = guild.icon.url if guild.icon else None
    buffer = await render_banner("🌳 ¿Necesitas Ayuda?", "SoulBot • Support", guild_icon)
    return discord.File(buffer, filename="ticket_banner.png")


class TicketSelect(discord.ui.Select):
    def __init__(self, categories: list[tuple[str, str]]):
        options = [
            discord.SelectOption(label=label, value=label, emoji=parse_emoji(emoji))
            for label, emoji in categories
        ] or [discord.SelectOption(label="Soporte", value="Soporte")]
        super().__init__(
            placeholder="Selecciona una categoría...",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="soulbot:ticket_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await open_or_queue_ticket(interaction, self.values[0])


class TicketPanelView(discord.ui.View):
    def __init__(self, categories: list[tuple[str, str]]):
        super().__init__(timeout=None)
        self.add_item(TicketSelect(categories))


class TicketControlView(discord.ui.View):
    def __init__(self, claimed: bool = False):
        super().__init__(timeout=None)
        if claimed:
            self.claim_btn.style = discord.ButtonStyle.secondary
            self.claim_btn.label = "Reclamado"
            self.claim_btn.disabled = True

    @discord.ui.button(label="Reclamar", emoji="🙋", style=discord.ButtonStyle.primary, custom_id="soulbot:ticket_claim")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await do_claim(interaction)

    @discord.ui.button(label="Cerrar", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="soulbot:ticket_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await do_close(interaction, "Cerrado desde el panel")


async def _staff_role(interaction: discord.Interaction) -> Optional[discord.Role]:
    config = await db.get_guild_config(interaction.guild_id)
    if not config["tickets_staff_role_id"]:
        return None
    return interaction.guild.get_role(config["tickets_staff_role_id"])


async def _is_staff(interaction: discord.Interaction) -> bool:
    role = await _staff_role(interaction)
    if role is None:
        return interaction.user.guild_permissions.manage_guild
    return role in interaction.user.roles or interaction.user.guild_permissions.manage_guild


async def open_or_queue_ticket(interaction: discord.Interaction, category: str):
    guild = interaction.guild
    config = await db.get_guild_config(guild.id)

    # cooldown 60s anti-spam panel
    now = time.time()
    last = _ticket_cooldown.get(interaction.user.id, 0)
    if now - last < 60:
        await interaction.response.send_message(embed=error_embed(f"Espera {int(60-(now-last))}s antes de abrir otro ticket (anti-spam)."), ephemeral=True)
        return
    _ticket_cooldown[interaction.user.id] = now

    existing = await db.get_open_ticket_for_user(guild.id, interaction.user.id)
    if existing:
        await interaction.response.send_message(
            embed=error_embed(f"Ya tienes un ticket abierto: <#{existing['channel_id']}>"), ephemeral=True
        )
        return

    open_count = await db.count_open_tickets(guild.id)
    if config["tickets_paused"] or open_count >= config["tickets_max_active"]:
        entry_id = await db.add_to_queue(guild.id, interaction.user.id, category)
        position = await db.get_queue_position(guild.id, entry_id)
        await interaction.response.send_message(
            embed=error_embed(
                f"Los tickets están al máximo ahora mismo. Te hemos puesto en cola.\n📊 Posición: **#{position}**",
                title="⏳ En cola",
            ),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    try:
        channel = await _create_ticket_channel(guild, interaction.user, category, config)
    except discord.Forbidden as e:
        await interaction.followup.send(embed=error_embed(f"No tengo permisos para crear el ticket. Verifica que tenga `Gestionar canales` en la categoría y en el servidor.\n`{e}`"), ephemeral=True)
        return
    except discord.HTTPException as e:
        await interaction.followup.send(embed=error_embed(f"Error de Discord al crear el canal del ticket.\n`{e}`"), ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(embed=error_embed(f"Error inesperado al crear el ticket.\n`{e}`"), ephemeral=True)
        return
    await interaction.followup.send(embed=success_embed(f"Ticket creado: {channel.mention}"), ephemeral=True)


async def _create_ticket_channel(guild: discord.Guild, member: discord.Member, category: str, config: dict, ping: bool = True) -> discord.TextChannel:
    parent = guild.get_channel(config["tickets_category_id"]) if config["tickets_category_id"] else None
    staff_role = guild.get_role(config["tickets_staff_role_id"]) if config["tickets_staff_role_id"] else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    safe_name = f"ticket-{member.name}"[:90].lower().replace(" ", "-")
    channel = await guild.create_text_channel(
        name=safe_name, category=parent if isinstance(parent, discord.CategoryChannel) else None, overwrites=overwrites,
        topic=f"Ticket de {member} • Categoría: {category}",
    )

    await db.create_ticket(guild.id, channel.id, member.id, category)

    from utils.emojis import emoji
    from utils.card_renderer import render_banner, category_accent

    accent = category_accent(category)
    banner_buf = await render_banner(category, f"Ticket de {member.display_name}", None, accent_hex=accent)
    banner_file = discord.File(banner_buf, filename="ticket_open.png")

    embed = base_embed(
        f"{emoji(guild, 'wave')} Hola {member.mention}, gracias por abrir un ticket.\n\n"
        "Un miembro del Staff te atenderá en breve. Mientras tanto, cuéntanos con detalle tu caso.",
        int(accent.lstrip("#"), 16),
        title=f"{emoji(guild, 'ticket')} Ticket abierto",
    )
    embed.set_image(url="attachment://ticket_open.png")
    if ping:
        mention = staff_role.mention if staff_role else ""
        content = f"{member.mention} {mention}".strip()
        await channel.send(content=content, embed=embed, view=TicketControlView(), file=banner_file)
    else:
        # fast: sin ping, solo embed
        await channel.send(embed=embed, view=TicketControlView(), file=banner_file)

    return channel


async def do_claim(interaction: discord.Interaction):
    ticket = await db.get_ticket_by_channel(interaction.channel_id)
    if not ticket:
        await interaction.response.send_message(embed=error_embed("Esto no es un canal de ticket."), ephemeral=True)
        return
    if not await _is_staff(interaction):
        await interaction.response.send_message(embed=error_embed("Solo el Staff puede reclamar tickets."), ephemeral=True)
        return
    if ticket["claimed_by"]:
        await interaction.response.send_message(
            embed=error_embed(f"Este ticket ya fue reclamado por <@{ticket['claimed_by']}>."), ephemeral=True
        )
        return

    await db.claim_ticket(interaction.channel_id, interaction.user.id)

    if interaction.message and interaction.message.components:
        try:
            await interaction.response.edit_message(view=TicketControlView(claimed=True))
            await interaction.followup.send(embed=success_embed(f"🙋 Ticket reclamado por {interaction.user.mention}."))
            return
        except discord.InteractionResponded:
            pass

    await interaction.response.send_message(embed=success_embed(f"🙋 Ticket reclamado por {interaction.user.mention}."))


async def do_close(interaction: discord.Interaction, reason: str):
    ticket = await db.get_ticket_by_channel(interaction.channel_id)
    if not ticket:
        await interaction.response.send_message(embed=error_embed("Esto no es un canal de ticket."), ephemeral=True)
        return

    is_staff = await _is_staff(interaction)
    if not is_staff and interaction.user.id != ticket["user_id"]:
        await interaction.response.send_message(embed=error_embed("No puedes cerrar este ticket."), ephemeral=True)
        return

    await interaction.response.send_message(embed=success_embed("🔒 Cerrando ticket y generando transcript..."))

    channel = interaction.channel
    guild = interaction.guild
    path = await generate_transcript(channel)
    await db.close_ticket(channel.id)

    config = await db.get_guild_config(guild.id)
    transcript_url = f"{PUBLIC_URL}/transcripts/{channel.id}.html"

    if config["tickets_log_channel_id"]:
        log_channel = guild.get_channel(config["tickets_log_channel_id"])
        if log_channel:
            embed = base_embed(
                f"👤 Usuario: <@{ticket['user_id']}>\n📂 Categoría: {ticket['category']}\n"
                f"🛡️ Cerrado por: {interaction.user.mention}\n📝 Razón: {reason}\n"
                f"🔗 [Ver transcript en HTML]({transcript_url})",
                COLOR_ERROR,
                title="🔒 Ticket cerrado",
            )
            await log_channel.send(embed=embed, file=discord.File(path))

    await asyncio.sleep(5)
    try:
        await channel.delete(reason="Ticket cerrado")
    except discord.Forbidden:
        pass

    # Atender a la cola si hay alguien esperando
    entry = await db.pop_queue(guild.id)
    if entry:
        member = guild.get_member(entry["user_id"])
        if member:
            new_channel = await _create_ticket_channel(guild, member, entry["category"], config)
            try:
                await member.send(f"🎫 Tu ticket ya está listo: {new_channel.jump_url}")
            except discord.Forbidden:
                pass


class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_close_loop.start()

    def cog_unload(self):
        try:
            self.auto_close_loop.cancel()
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        try:
            t = await db.get_ticket_by_channel(message.channel.id)
            if t and t["status"] == "open":
                await db.update_ticket_activity(message.channel.id)
        except Exception:
            pass

    @tasks.loop(hours=6)
    async def auto_close_loop(self):
        # Cierra tickets inactivos 48h (anti-acumulación)
        try:
            stale = await db.get_stale_tickets(48)
            for t in stale[:10]:
                guild = self.bot.get_guild(t["guild_id"])
                if not guild:
                    await db.close_ticket(t["channel_id"])
                    continue
                channel = guild.get_channel(t["channel_id"])
                # genera transcript si existe canal
                try:
                    if channel:
                        path = await generate_transcript(channel)  # type: ignore
                        config = await db.get_guild_config(guild.id)
                        if config.get("tickets_log_channel_id"):
                            log_ch = guild.get_channel(config["tickets_log_channel_id"])
                            if log_ch:
                                url = f"{PUBLIC_URL}/transcripts/{t['channel_id']}.html"
                                emb = base_embed(f"👤 <@{t['user_id']}> • 📂 {t['category']} • auto-cierre 48h inactividad\n🔗 [Transcript]({url})", COLOR_ERROR, title="🔒 Ticket auto-cerrado")
                                await log_ch.send(embed=emb, file=discord.File(path))
                        await db.close_ticket(t["channel_id"])
                        try: await channel.delete(reason="Auto-close 48h inactividad")  # type: ignore
                        except Exception: pass
                    else:
                        await db.close_ticket(t["channel_id"])
                except Exception:
                    continue
                # atiende cola tras cerrar
                try:
                    config = await db.get_guild_config(t["guild_id"])
                    entry = await db.pop_queue(t["guild_id"])
                    if entry and guild:
                        member = guild.get_member(entry["user_id"])
                        if member:
                            nc = await _create_ticket_channel(guild, member, entry["category"], config)
                            try: await member.send(f"🎫 Tu ticket ya está listo: {nc.jump_url}")
                            except discord.Forbidden: pass
                except Exception:
                    pass
        except Exception:
            pass

    @auto_close_loop.before_loop
    async def before_auto_close(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        # Vista persistente genérica: debe registrarse siempre, sin depender de bot.guilds
        # (setup_hook se ejecuta antes de que los guilds estén en caché, por eso fallaba y el select parecía "roto").
        # Usamos categorías por defecto; el panel real enviado por /setup tickets lleva las categorías actuales.
        try:
            self.bot.add_view(TicketPanelView([("Soporte", "🎫"), ("Reportes", "🚨"), ("Otro", "❓")]))
        except Exception:
            pass
        try:
            self.bot.add_view(TicketControlView())
        except Exception:
            pass
        # Además intenta re-registrar por cada guild ya configurado (para logs de compatibilidad)
        for guild in list(self.bot.guilds):
            try:
                config = await db.get_guild_config(guild.id)
                if config.get("tickets_panel_channel_id"):
                    self.bot.add_view(TicketPanelView(load_categories(config)))
            except Exception:
                pass

    ticket_group = app_commands.Group(name="ticket", description="Comandos para gestionar el ticket actual")

    @ticket_group.command(name="claim", description="Reclama el ticket actual")
    async def claim(self, interaction: discord.Interaction):
        await do_claim(interaction)

    @ticket_group.command(name="unclaim", description="Deja de estar a cargo del ticket actual")
    async def unclaim(self, interaction: discord.Interaction):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Esto no es un canal de ticket."), ephemeral=True)
            return
        if ticket["claimed_by"] != interaction.user.id and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo quien reclamó el ticket puede liberarlo."), ephemeral=True)
            return

        await db.db().execute("UPDATE tickets SET claimed_by = NULL WHERE channel_id = ?", (interaction.channel_id,))
        await db.db().commit()
        await interaction.response.send_message(embed=success_embed("Ticket liberado, cualquiera del Staff puede reclamarlo."))

    @ticket_group.command(name="transferclaim", description="Transfiere el ticket actual a otro miembro del Staff")
    @app_commands.describe(usuario="Nuevo responsable del ticket")
    async def transferclaim(self, interaction: discord.Interaction, usuario: discord.Member):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Esto no es un canal de ticket."), ephemeral=True)
            return
        if not await _is_staff(interaction):
            await interaction.response.send_message(embed=error_embed("Solo el Staff puede transferir tickets."), ephemeral=True)
            return

        await db.claim_ticket(interaction.channel_id, usuario.id)
        await interaction.response.send_message(embed=success_embed(f"Ticket transferido a {usuario.mention}."))

    @ticket_group.command(name="adduser", description="Añade a un usuario al ticket actual")
    @app_commands.describe(usuario="Usuario a añadir")
    async def adduser(self, interaction: discord.Interaction, usuario: discord.Member):
        ticket = await db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message(embed=error_embed("Esto no es un canal de ticket."), ephemeral=True)
            return
        if not (await _is_staff(interaction) or interaction.user.id == ticket["user_id"]):
            await interaction.response.send_message(embed=error_embed("No tienes permiso para añadir usuarios aquí."), ephemeral=True)
            return

        await interaction.channel.set_permissions(usuario, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} añadido al ticket."))

    @ticket_group.command(name="fcreate", description="Crea un ticket rápido sin ping (fast)")
    @app_commands.describe(categoria="Categoría (opcional, usa la primera por defecto)", usuario="Usuario para el que crear (solo Staff, opcional)")
    async def fcreate(self, interaction: discord.Interaction, categoria: str | None = None, usuario: discord.Member | None = None):
        # cooldown 30s anti-spam fcreate
        now = time.time()
        last = _FCREATE_COOLDOWN.get(interaction.user.id, 0)
        if now - last < 30:
            await interaction.response.send_message(embed=error_embed(f"Espera {int(30-(now-last))}s antes de otro fcreate."), ephemeral=True)
            return
        _FCREATE_COOLDOWN[interaction.user.id] = now
        # Fast path: sin ping, sin cola si es fcreate (bypass pausado/max), sin mención ruidosa
        guild = interaction.guild
        config = await db.get_guild_config(guild.id)
        # si usuario especificado, solo Staff puede usarlo
        target: discord.Member = interaction.user  # type: ignore
        if usuario is not None:
            if not await _is_staff(interaction):
                await interaction.response.send_message(embed=error_embed("Solo el Staff puede crear tickets para otro usuario."), ephemeral=True)
                return
            target = usuario

        # si ya tiene ticket abierto
        existing = await db.get_open_ticket_for_user(guild.id, target.id)
        if existing:
            await interaction.response.send_message(embed=error_embed(f"{target.mention} ya tiene un ticket abierto: <#{existing['channel_id']}>"), ephemeral=True)
            return

        # categoría: la solicitada, o la primera disponible de la config
        cat_label = categoria.strip() if categoria else None
        if not cat_label:
            cats = load_categories(config)
            cat_label = cats[0][0] if cats else "Soporte"

        await interaction.response.defer(ephemeral=True)
        try:
            channel = await _create_ticket_channel(guild, target, cat_label, config, ping=False)
        except discord.Forbidden as e:
            await interaction.followup.send(embed=error_embed(f"No tengo permisos para crear el ticket.\n`{e}`"), ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(embed=error_embed(f"Error de Discord al crear el canal.\n`{e}`"), ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Error inesperado.\n`{e}`"), ephemeral=True)
            return
        await interaction.followup.send(embed=success_embed(f"Ticket creado (fast, sin ping): {channel.mention} para {target.mention}"), ephemeral=True)

    @ticket_group.command(name="close", description="Cierra el ticket actual y genera el transcript")
    @app_commands.describe(razon="Motivo del cierre (opcional)")
    async def close(self, interaction: discord.Interaction, razon: str = "Sin razón especificada"):
        await do_close(interaction, razon)

    @ticket_group.command(name="commands", description="Muestra los comandos del sistema de tickets")
    async def commands_help(self, interaction: discord.Interaction):
        embed = base_embed(
            "🎫 `/ticket claim` — reclama el ticket actual\n"
            "🔓 `/ticket unclaim` — libera el ticket que reclamaste\n"
            "🔁 `/ticket transferclaim usuario` — transfiere el ticket a otro Staff\n"
            "➕ `/ticket adduser usuario` — añade a alguien al ticket\n"
            "🔒 `/ticket close razon?` — cierra el ticket y genera transcript\n"
            "📊 `/ticket stats` — estadísticas del sistema (Staff)\n"
            "⚙️ `/setup tickets` — configuración (Staff)",
            COLOR,
            title="📋 Comandos de Tickets",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_group.command(name="stats", description="Estadísticas del sistema de tickets (Staff)")
    async def stats(self, interaction: discord.Interaction):
        if not await _is_staff(interaction):
            await interaction.response.send_message(embed=error_embed("Solo el Staff puede ver las estadísticas."), ephemeral=True)
            return

        data = await db.get_ticket_stats(interaction.guild_id)

        def fmt_minutes(m):
            if m is None:
                return "Sin datos"
            if m < 60:
                return f"{m:.0f} min"
            return f"{m / 60:.1f} h"

        top_lines = "\n".join(f"<@{staff_id}> — {count} tickets" for staff_id, count in data["top_staff"]) or "Sin datos todavía"

        embed = base_embed(
            f"🎫 Tickets abiertos ahora: **{data['open']}**\n"
            f"✅ Cerrados hoy: **{data['closed_today']}**\n"
            f"⏱️ Tiempo medio hasta reclamar: **{fmt_minutes(data['avg_claim_minutes'])}**\n"
            f"⏳ Tiempo medio de resolución: **{fmt_minutes(data['avg_resolution_minutes'])}**\n\n"
            f"🏆 **Top Staff (tickets atendidos):**\n{top_lines}",
            COLOR,
            title="📊 Estadísticas de Tickets",
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
