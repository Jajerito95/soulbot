from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands

from database import db, get_guild_config
from utils.embeds import error_embed, success_embed
from cogs.welcome import DEFAULT_WELCOME, build_welcome_embed
from cogs.suggestions import build_suggestion_embed, SuggestionView


class TestCog(commands.Cog):
    """Comandos para probar sistemas sin esperar eventos reales. Solo Staff."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    test_group = app_commands.Group(
        name="test",
        description="Prueba los sistemas de SoulBot (Staff)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @test_group.command(name="welcome", description="Simula tu propia bienvenida en el canal configurado")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test_welcome(self, interaction: discord.Interaction):
        config = await get_guild_config(interaction.guild_id)

        if not config["welcome_channel_id"]:
            await interaction.response.send_message(
                embed=error_embed("No hay canal de bienvenida configurado. Usa `/setup invites` primero."),
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(config["welcome_channel_id"])
        if channel is None:
            await interaction.response.send_message(
                embed=error_embed("El canal configurado ya no existe."), ephemeral=True
            )
            return

        template = config["welcome_message"] or DEFAULT_WELCOME
        embed = build_welcome_embed(interaction.user, template)
        embed.set_footer(text="SoulBot System • Prueba, no cuenta como miembro nuevo")

        await channel.send(embed=embed)
        estado = "✅ activado" if config["welcome_enabled"] else "⚠️ desactivado (no se enviaría en un ingreso real)"
        await interaction.response.send_message(
            embed=success_embed(f"Bienvenida de prueba enviada en {channel.mention}.\nEstado del sistema: {estado}"),
            ephemeral=True,
        )

    @test_group.command(name="suggestion", description="Crea una sugerencia de prueba en este canal")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(content="Contenido de la sugerencia de prueba (opcional)")
    async def test_suggestion(self, interaction: discord.Interaction, content: str = "Esto es una sugerencia de prueba 🧪"):
        embed = build_suggestion_embed(content, interaction.user, "pending", 0, 0)
        embed.set_footer(text=f"Propuesta por: {interaction.user.display_name} • Prueba")

        await interaction.response.send_message(embed=embed, view=SuggestionView())
        message = await interaction.original_response()

        await db().execute(
            "INSERT INTO suggestions (message_id, guild_id, author_id, content) VALUES (?, ?, ?, ?)",
            (message.id, interaction.guild_id, interaction.user.id, content),
        )
        await db().commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(TestCog(bot))
