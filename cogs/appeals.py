from __future__ import annotations
from typing import Optional
import re

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from utils.sanctions_engine import is_imgur
from config import COLOR, COLOR_ERROR, COLOR_SUCCESS


def build_appeal_embed(appeal: dict, sanction: dict, user: discord.abc.User) -> discord.Embed:
    status_map = {
        "pending": ("🕐 Pendiente", COLOR),
        "approved": ("✅ Aprobada", COLOR_SUCCESS),
        "denied": ("❌ Denegada", COLOR_ERROR),
    }
    status_text, color = status_map.get(appeal.get("status") or "pending", status_map["pending"])

    embed = base_embed(
        f"👤 Usuario: <@{user.id}> (`{user.id}`)\n"
        f"⚖️ Sanción apelada: `#{sanction['id']}` — **{sanction['action'].upper()}**\n"
        f"📝 Razón original: {sanction['reason'] or 'Sin razón'}\n\n"
        f"💬 **Motivo de la apelación:**\n{appeal['reason']}",
        color,
        title=f"📮 Apelación #{appeal['id']}",
    )
    if appeal["evidence_url"]:
        embed.add_field(name="🔗 Evidencia", value=appeal["evidence_url"], inline=False)
    embed.add_field(name="📌 Estado", value=status_text, inline=False)
    if appeal["reviewed_by"]:
        embed.add_field(name="🛡️ Revisada por", value=f"<@{appeal['reviewed_by']}>", inline=False)
    return embed


class AppealsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    appeal_group = app_commands.Group(name="appeal", description="Sistema de apelaciones de sanciones")

    @appeal_group.command(name="create", description="Apela una sanción que recibiste")
    @app_commands.describe(
        sancion_id="ID de la sanción (mira /sanction info)",
        razon="Explica por qué crees que la sanción debería revisarse",
        evidencia="Link de Imgur con evidencia (opcional)",
    )
    async def create(self, interaction: discord.Interaction, sancion_id: int, razon: str, evidencia: Optional[str] = None):
        if evidencia and not is_imgur(evidencia):
            await interaction.response.send_message(embed=error_embed("La evidencia debe ser un link de Imgur (imgur.com)."), ephemeral=True)
            return

        sanction = await db.get_sanction_by_id(interaction.guild_id, sancion_id)
        if not sanction:
            await interaction.response.send_message(embed=error_embed("No existe ninguna sanción con ese ID."), ephemeral=True)
            return
        if sanction["target_id"] != interaction.user.id:
            await interaction.response.send_message(embed=error_embed("Solo puedes apelar sanciones que te afecten a ti."), ephemeral=True)
            return

        existing = await db.get_pending_appeal_for_sanction(interaction.guild_id, sancion_id)
        if existing:
            await interaction.response.send_message(embed=error_embed(f"Ya tienes una apelación pendiente (`#{existing['id']}`) para esta sanción."), ephemeral=True)
            return

        appeal_id = await db.create_appeal(interaction.guild_id, sancion_id, interaction.user.id, razon, evidencia)
        appeal = await db.get_appeal(appeal_id)

        await interaction.response.send_message(embed=success_embed(f"Apelación enviada. ID: `#{appeal_id}`. El Staff la revisará pronto."), ephemeral=True)

        config = await db.get_guild_config(interaction.guild_id)
        if config["appeals_channel_id"]:
            channel = interaction.guild.get_channel(config["appeals_channel_id"])
            if channel:
                embed = build_appeal_embed(appeal, sanction, interaction.user)
                await channel.send(embed=embed, view=AppealReviewView())

    @appeal_group.command(name="status", description="Consulta el estado de tus apelaciones")
    async def status(self, interaction: discord.Interaction):
        appeals = await db.get_user_appeals(interaction.guild_id, interaction.user.id)
        if not appeals:
            await interaction.response.send_message(embed=error_embed("No has enviado ninguna apelación."), ephemeral=True)
            return

        icons = {"pending": "🕐", "approved": "✅", "denied": "❌"}
        lines = [f"{icons[a['status']]} `#{a['id']}` — sanción `#{a['sanction_id']}` — **{a['status']}**" for a in appeals[:10]]
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title="📮 Tus apelaciones"), ephemeral=True)

    @appeal_group.command(name="history", description="[Staff] Historial de apelaciones de un usuario")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(usuario="Usuario a consultar")
    async def history(self, interaction: discord.Interaction, usuario: discord.Member):
        appeals = await db.get_user_appeals(interaction.guild_id, usuario.id)
        if not appeals:
            await interaction.response.send_message(embed=error_embed(f"{usuario.mention} no tiene apelaciones."))
            return

        icons = {"pending": "🕐", "approved": "✅", "denied": "❌"}
        lines = [f"{icons[a['status']]} `#{a['id']}` — sanción `#{a['sanction_id']}` — **{a['status']}**" for a in appeals[:10]]
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title=f"📮 Apelaciones de {usuario.display_name}"))


class AppealReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _resolve(self, interaction: discord.Interaction, status: str):
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message(embed=error_embed("Solo el Staff puede revisar apelaciones."), ephemeral=True)
            return

        # El ID de la apelación va en el título del embed original: "📮 Apelación #N"
        title = interaction.message.embeds[0].title
        appeal_id = int(title.split("#")[1])
        appeal = await db.get_appeal(appeal_id)

        if not appeal or appeal["status"] != "pending":
            await interaction.response.send_message(embed=error_embed("Esta apelación ya fue revisada."), ephemeral=True)
            return

        await db.resolve_appeal(appeal_id, status, interaction.user.id)
        sanction = await db.get_sanction_by_id(interaction.guild_id, appeal["sanction_id"])

        if status == "approved" and sanction and sanction["action"] == "ban":
            try:
                await interaction.guild.unban(discord.Object(id=appeal["user_id"]), reason=f"Apelación #{appeal_id} aprobada")
            except (discord.NotFound, discord.Forbidden):
                pass
            await db.remove_temp_ban(interaction.guild_id, appeal["user_id"])

        try:
            user = await interaction.client.fetch_user(appeal["user_id"])
            result_text = "aprobada ✅" if status == "approved" else "denegada ❌"
            await user.send(f"📮 Tu apelación `#{appeal_id}` en **{interaction.guild.name}** ha sido **{result_text}**.")
        except (discord.NotFound, discord.Forbidden):
            user = None

        appeal = await db.get_appeal(appeal_id)
        embed = build_appeal_embed(appeal, sanction, user or discord.Object(id=appeal["user_id"]))
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Aprobar", emoji="✅", style=discord.ButtonStyle.success, custom_id="soulbot:appeal_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "approved")

    @discord.ui.button(label="Denegar", emoji="❌", style=discord.ButtonStyle.danger, custom_id="soulbot:appeal_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "denied")


# ---------- botón de apelación directo en el DM de sanción ----------

class AppealModal(discord.ui.Modal, title="Apelar sanción"):
    reason_input = discord.ui.TextInput(
        label="¿Por qué crees que fue injusta?", style=discord.TextStyle.paragraph, max_length=1000
    )
    evidence_input = discord.ui.TextInput(label="Evidencia (link de Imgur, opcional)", required=False)

    def __init__(self, guild_id: int, sanction_id: int):
        super().__init__()
        self.guild_id = guild_id
        self.sanction_id = sanction_id

    async def on_submit(self, interaction: discord.Interaction):
        evidencia = self.evidence_input.value or None
        if evidencia and not is_imgur(evidencia):
            await interaction.response.send_message(embed=error_embed("La evidencia debe ser un link de Imgur (imgur.com)."), ephemeral=True)
            return

        sanction = await db.get_sanction_by_id(self.guild_id, self.sanction_id)
        if not sanction:
            await interaction.response.send_message(embed=error_embed("Esa sanción ya no existe."), ephemeral=True)
            return
        if sanction["target_id"] != interaction.user.id:
            await interaction.response.send_message(embed=error_embed("Esta sanción no te pertenece."), ephemeral=True)
            return

        existing = await db.get_pending_appeal_for_sanction(self.guild_id, self.sanction_id)
        if existing:
            await interaction.response.send_message(embed=error_embed(f"Ya tienes una apelación pendiente (`#{existing['id']}`)."), ephemeral=True)
            return

        appeal_id = await db.create_appeal(self.guild_id, self.sanction_id, interaction.user.id, self.reason_input.value, evidencia)
        appeal = await db.get_appeal(appeal_id)

        await interaction.response.send_message(embed=success_embed(f"📮 Apelación enviada. ID: `#{appeal_id}`. El Staff la revisará pronto."), ephemeral=True)

        guild = interaction.client.get_guild(self.guild_id)
        if guild:
            config = await db.get_guild_config(self.guild_id)
            if config["appeals_channel_id"]:
                channel = guild.get_channel(config["appeals_channel_id"])
                if channel:
                    embed = build_appeal_embed(appeal, sanction, interaction.user)
                    await channel.send(embed=embed, view=AppealReviewView())


class AppealButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"soulbot:appeal_start:(?P<guild_id>\d+):(?P<sanction_id>\d+)",
):
    def __init__(self, guild_id: int, sanction_id: int):
        super().__init__(
            discord.ui.Button(
                label="¿Fue injusto? Apela aquí",
                emoji="📮",
                style=discord.ButtonStyle.secondary,
                custom_id=f"soulbot:appeal_start:{guild_id}:{sanction_id}",
            )
        )
        self.guild_id = guild_id
        self.sanction_id = sanction_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(int(match["guild_id"]), int(match["sanction_id"]))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AppealModal(self.guild_id, self.sanction_id))


class AppealPromptView(discord.ui.View):
    """Vista adjunta al DM de sanción, con el botón para apelar directamente."""
    def __init__(self, guild_id: int, sanction_id: int):
        super().__init__(timeout=None)
        self.add_item(AppealButton(guild_id, sanction_id))


async def setup(bot: commands.Bot):
    bot.add_view(AppealReviewView())
    bot.add_dynamic_items(AppealButton)
    await bot.add_cog(AppealsCog(bot))
