from __future__ import annotations
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import base_embed, error_embed, success_embed, is_valid_hex, hex_to_int
from config import COLOR


class EmbedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="embed", description="Crea un embed personalizado")
    @app_commands.describe(
        description="Contenido del embed",
        title="Título del embed (opcional)",
        color="Color en formato HEX, ej: #5865F2 (opcional)",
        footer="Pie de página (opcional)",
    )
    async def embed(
        self,
        interaction: discord.Interaction,
        description: str,
        title: Optional[str] = None,
        color: Optional[str] = None,
        footer: Optional[str] = None,
    ):
        final_color = COLOR
        if color:
            if not is_valid_hex(color):
                await interaction.response.send_message(
                    embed=error_embed(f"El color `{color}` no es un HEX válido. Ejemplo: `#5865F2`"),
                    ephemeral=True,
                )
                return
            final_color = hex_to_int(color)

        result = base_embed(description, final_color, title, footer)
        await interaction.channel.send(embed=result)
        await interaction.response.send_message(
            embed=success_embed("El embed ha sido enviado al canal.", "✨ Embed creado correctamente"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedCog(bot))
