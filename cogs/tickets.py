from __future__ import annotations
import json
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from utils.transcripts import generate_transcript
from config import COLOR, COLOR_ERROR, PUBLIC_URL


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
    embed.set_author(name="SoulBot • Support")
    embed.title = "🌳 ¿Necesitas Ayuda?"
    embed.description = (
        "Abre un ticket en la categoría correspondiente y sé paciente. "
        "La impaciencia o abrir tickets innecesarios resultará en sanciones."
    )
    embed.add_field(name="🔔 Reglas de Tickets", value="\u200b", inline=False)
    embed.add_field(name="1️⃣ Ten paciencia", value="Espera un tiempo razonable para que tu ticket sea atendido.", inline=False)
    embed.add_field(name="2️⃣ Respeta al equipo del staff", value="No insultes ni faltes al respeto a los miembros del equipo.", inline=False)
    embed.add_field(name="3️⃣ Mantente activo en el ticket", value="Responde oportunamente para evitar que tu ticket sea cerrado por inactividad.", inline=False)
    embed.add_field(name="4️⃣ Elige la categoría correcta", value="Abre tickets en la categoría adecuada para evitar sanciones.", inline=False)
    embed.add_field(name="5️⃣ Evita abrir tickets sin motivo", value="Los tickets sin razón válida son sancionables.", inline=False)
    embed.add_field(name="🙏 Te atenderemos lo más rápido posible", value="Gracias por tu paciencia y comprensión.", inline=False)
    embed.set_footer(text="SoulSeeker™ | All rights reserved.")
    return embed


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
    def __init__(self):
        super().__init__(timeout=None)

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
    channel = await _create_ticket_channel(guild, interaction.user, category, config)
    await interaction.followup.send(embed=success_embed(f"Ticket creado: {channel.mention}"), ephemeral=True)


async def _create_ticket_channel(guild: discord.Guild, member: discord.Member, category: str, config: dict) -> discord.TextChannel:
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

    embed = base_embed(
        f"👋 Hola {member.mention}, gracias por abrir un ticket.\n📂 Categoría: **{category}**\n\n"
        "Un miembro del Staff te atenderá en breve. Mientras tanto, cuéntanos con detalle tu caso.",
        COLOR,
        title="🎫 Ticket abierto",
    )
    mention = staff_role.mention if staff_role else ""
    await channel.send(content=f"{member.mention} {mention}".strip(), embed=embed, view=TicketControlView())

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

    async def cog_load(self):
        # Re-registra los paneles persistentes de todos los servidores configurados
        for guild in self.bot.guilds:
            config = await db.get_guild_config(guild.id)
            if config["tickets_panel_channel_id"]:
                self.bot.add_view(TicketPanelView(load_categories(config)))
        self.bot.add_view(TicketControlView())

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
            "⚙️ `/setup tickets` — configuración (Staff)",
            COLOR,
            title="📋 Comandos de Tickets",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
