from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands

from database import db, get_guild_config, get_user_vote, set_user_vote
from utils.embeds import error_embed
from config import COLOR, COLOR_SUCCESS, COLOR_ERROR

STATUS_MAP = {
    "pending": ("⏳ Pendiente", COLOR),
    "approved": ("🟢 Aprobada por Staff", COLOR_SUCCESS),
    "denied": ("🔴 Denegada por Staff", COLOR_ERROR),
}


def build_suggestion_embed(content: str, author: discord.abc.User, status: str, yes: int, no: int) -> discord.Embed:
    status_text, color = STATUS_MAP[status]
    embed = discord.Embed(title="💡 Sugerencia", description=content, color=color)
    embed.add_field(name="🟢 Sí", value=str(yes), inline=True)
    embed.add_field(name="🔴 No", value=str(no), inline=True)
    embed.add_field(name="Estado", value=status_text, inline=False)
    embed.set_footer(text=f"Propuesta por: {author.display_name} • SoulBot System", icon_url=author.display_avatar.url)
    embed.timestamp = discord.utils.utcnow()
    return embed


class SuggestionView(discord.ui.View):
    """Vista persistente: votos públicos + resolución de Staff en un único mensaje."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _get_suggestion(self, message_id: int):
        cur = await db().execute(
            "SELECT content, author_id, status, yes_votes, no_votes FROM suggestions WHERE message_id = ?",
            (message_id,),
        )
        return await cur.fetchone()

    async def _refresh(self, interaction, status, yes, no, content, author_id):
        author = interaction.guild.get_member(author_id) or interaction.user
        embed = build_suggestion_embed(content, author, status, yes, no)
        view = self if status == "pending" else None
        await interaction.response.edit_message(embed=embed, view=view)

    async def _vote(self, interaction: discord.Interaction, vote: str):
        message_id = interaction.message.id
        row = await self._get_suggestion(message_id)
        if row is None:
            await interaction.response.send_message(embed=error_embed("Sugerencia no encontrada."), ephemeral=True)
            return
        content, author_id, status, yes, no = row

        if status != "pending":
            await interaction.response.send_message(
                embed=error_embed("Esta sugerencia ya ha sido resuelta."), ephemeral=True
            )
            return

        previous_vote = await get_user_vote(message_id, interaction.user.id)

        if previous_vote == vote:
            # Ya votó lo mismo: no sumar de nuevo, solo confirmar en silencio.
            await interaction.response.defer()
            return

        field = "yes_votes" if vote == "yes" else "no_votes"
        opposite_field = "no_votes" if vote == "yes" else "yes_votes"

        if previous_vote is None:
            await db().execute(f"UPDATE suggestions SET {field} = {field} + 1 WHERE message_id = ?", (message_id,))
        else:
            # Cambia su voto anterior: resta del campo opuesto y suma al nuevo.
            await db().execute(
                f"UPDATE suggestions SET {field} = {field} + 1, {opposite_field} = MAX({opposite_field} - 1, 0) "
                f"WHERE message_id = ?",
                (message_id,),
            )
        await db().commit()
        await set_user_vote(message_id, interaction.user.id, vote)

        content, author_id, status, yes, no = await self._get_suggestion(message_id)

        config = await get_guild_config(interaction.guild_id)
        if config["auto_approve_votes"] and yes >= config["auto_approve_votes"]:
            status = "approved"
        elif config["auto_deny_votes"] and no >= config["auto_deny_votes"]:
            status = "denied"

        if status != "pending":
            await db().execute("UPDATE suggestions SET status = ? WHERE message_id = ?", (status, message_id))
            await db().commit()

        await self._refresh(interaction, status, yes, no, content, author_id)

    async def _resolve(self, interaction: discord.Interaction, status: str):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=error_embed("Solo el Staff puede resolver sugerencias."), ephemeral=True
            )
            return

        message_id = interaction.message.id
        row = await self._get_suggestion(message_id)
        if row is None:
            return
        content, author_id, _status, yes, no = row

        await db().execute("UPDATE suggestions SET status = ? WHERE message_id = ?", (status, message_id))
        await db().commit()

        await self._refresh(interaction, status, yes, no, content, author_id)

    @discord.ui.button(label="Sí", emoji="🟢", style=discord.ButtonStyle.success, custom_id="soulbot:vote_yes", row=0)
    async def vote_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, "yes")

    @discord.ui.button(label="No", emoji="🔴", style=discord.ButtonStyle.danger, custom_id="soulbot:vote_no", row=0)
    async def vote_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, "no")

    @discord.ui.button(label="Aprobar (Staff)", style=discord.ButtonStyle.secondary, custom_id="soulbot:staff_approve", row=1)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "approved")

    @discord.ui.button(label="Denegar (Staff)", style=discord.ButtonStyle.secondary, custom_id="soulbot:staff_deny", row=1)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "denied")


class SuggestionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(SuggestionView())

    @app_commands.command(name="suggestion", description="Envía una sugerencia al canal correspondiente")
    @app_commands.describe(content="Contenido de tu sugerencia")
    async def suggestion(self, interaction: discord.Interaction, content: str):
        config = await get_guild_config(interaction.guild_id)
        allowed_channel = config["suggestion_channel_id"]

        if not allowed_channel or interaction.channel_id != allowed_channel:
            channel_mention = f"<#{allowed_channel}>" if allowed_channel else "el canal configurado"
            await interaction.response.send_message(
                embed=error_embed(f"Este comando solo puede usarse en {channel_mention}."),
                ephemeral=True,
            )
            return

        embed = build_suggestion_embed(content, interaction.user, "pending", 0, 0)
        await interaction.response.send_message(embed=embed, view=SuggestionView())
        message = await interaction.original_response()

        await db().execute(
            "INSERT INTO suggestions (message_id, guild_id, author_id, content) VALUES (?, ?, ?, ?)",
            (message.id, interaction.guild_id, interaction.user.id, content),
        )
        await db().commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(SuggestionsCog(bot))
