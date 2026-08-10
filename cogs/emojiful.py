from __future__ import annotations
import re
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

EMOJI_RE = re.compile(r"<(a?):(\w{2,32}):(\d+)>")
NAME_RE = re.compile(r"^\w{2,32}$")


async def _download(url: str) -> Optional[bytes]:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            return await resp.read()


class EmojifulCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    emoji_group = app_commands.Group(name="emoji", description="Gestión de emojis del servidor")

    @emoji_group.command(name="add", description="Añade un emoji nuevo desde una imagen o una URL")
    @app_commands.checks.has_permissions(manage_emojis_and_stickers=True)
    @app_commands.describe(nombre="Nombre del emoji", imagen="Archivo de imagen", url="URL de la imagen (si no adjuntas archivo)")
    async def emoji_add(
        self,
        interaction: discord.Interaction,
        nombre: str,
        imagen: Optional[discord.Attachment] = None,
        url: Optional[str] = None,
    ):
        if not NAME_RE.match(nombre):
            await interaction.response.send_message(
                embed=error_embed("El nombre solo puede tener letras, números y `_` (2-32 caracteres)."),
                ephemeral=True,
            )
            return

        if imagen is None and not url:
            await interaction.response.send_message(
                embed=error_embed("Adjunta una imagen o proporciona una URL."), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        image_bytes = await imagen.read() if imagen else await _download(url)

        if image_bytes is None:
            await interaction.followup.send(embed=error_embed("No se pudo descargar la imagen."))
            return

        try:
            emoji = await interaction.guild.create_custom_emoji(name=nombre, image=image_bytes)
        except discord.HTTPException as e:
            await interaction.followup.send(embed=error_embed(f"Discord rechazó el emoji: {e.text}"))
            return

        await interaction.followup.send(embed=success_embed(f"{emoji} añadido como `:{emoji.name}:`", title="✨ Emoji creado"))

    @emoji_group.command(name="steal", description="Copia un emoji existente (pégalo tal cual, ej: <:nombre:12345>)")
    @app_commands.checks.has_permissions(manage_emojis_and_stickers=True)
    @app_commands.describe(emoji="El emoji a copiar", nombre="Nuevo nombre (opcional, usa el original si se omite)")
    async def emoji_steal(self, interaction: discord.Interaction, emoji: str, nombre: Optional[str] = None):
        match = EMOJI_RE.search(emoji)
        if not match:
            await interaction.response.send_message(
                embed=error_embed("Eso no parece un emoji personalizado. Debe verse como `<:nombre:123456>`."),
                ephemeral=True,
            )
            return

        animated, original_name, emoji_id = match.groups()
        final_name = nombre or original_name
        if not NAME_RE.match(final_name):
            await interaction.response.send_message(
                embed=error_embed("El nombre solo puede tener letras, números y `_` (2-32 caracteres)."),
                ephemeral=True,
            )
            return

        ext = "gif" if animated else "png"
        image_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"

        await interaction.response.defer(ephemeral=True)
        image_bytes = await _download(image_url)
        if image_bytes is None:
            await interaction.followup.send(embed=error_embed("No se pudo descargar ese emoji."))
            return

        try:
            new_emoji = await interaction.guild.create_custom_emoji(name=final_name, image=image_bytes)
        except discord.HTTPException as e:
            await interaction.followup.send(embed=error_embed(f"Discord rechazó el emoji: {e.text}"))
            return

        await interaction.followup.send(
            embed=success_embed(f"{new_emoji} copiado como `:{new_emoji.name}:`", title="✨ Emoji robado")
        )

    @emoji_group.command(name="remove", description="Elimina un emoji del servidor")
    @app_commands.checks.has_permissions(manage_emojis_and_stickers=True)
    @app_commands.describe(nombre="Nombre exacto del emoji a eliminar")
    async def emoji_remove(self, interaction: discord.Interaction, nombre: str):
        target = discord.utils.get(interaction.guild.emojis, name=nombre)
        if not target:
            await interaction.response.send_message(
                embed=error_embed(f"No existe un emoji llamado `:{nombre}:` en este servidor."), ephemeral=True
            )
            return

        await target.delete()
        await interaction.response.send_message(embed=success_embed(f"Emoji `:{nombre}:` eliminado."))

    @emoji_group.command(name="rename", description="Renombra un emoji existente")
    @app_commands.checks.has_permissions(manage_emojis_and_stickers=True)
    @app_commands.describe(nombre_actual="Nombre actual del emoji", nombre_nuevo="Nuevo nombre")
    async def emoji_rename(self, interaction: discord.Interaction, nombre_actual: str, nombre_nuevo: str):
        if not NAME_RE.match(nombre_nuevo):
            await interaction.response.send_message(
                embed=error_embed("El nombre solo puede tener letras, números y `_` (2-32 caracteres)."),
                ephemeral=True,
            )
            return

        target = discord.utils.get(interaction.guild.emojis, name=nombre_actual)
        if not target:
            await interaction.response.send_message(
                embed=error_embed(f"No existe un emoji llamado `:{nombre_actual}:` en este servidor."), ephemeral=True
            )
            return

        await target.edit(name=nombre_nuevo)
        await interaction.response.send_message(embed=success_embed(f"Renombrado a `:{nombre_nuevo}:` {target}"))

    @emoji_group.command(name="list", description="Lista todos los emojis del servidor")
    async def emoji_list(self, interaction: discord.Interaction):
        emojis = interaction.guild.emojis
        if not emojis:
            await interaction.response.send_message(embed=error_embed("Este servidor no tiene emojis personalizados."))
            return

        static = [str(e) for e in emojis if not e.animated]
        animated = [str(e) for e in emojis if e.animated]

        description = ""
        if static:
            description += "**Estáticos:**\n" + " ".join(static) + "\n\n"
        if animated:
            description += "**Animados:**\n" + " ".join(animated)

        embed = base_embed(description[:4000], COLOR, title=f"😀 Emojis de {interaction.guild.name} ({len(emojis)})")
        await interaction.response.send_message(embed=embed)

    @emoji_group.command(name="info", description="Muestra información de un emoji")
    @app_commands.describe(nombre="Nombre exacto del emoji")
    async def emoji_info(self, interaction: discord.Interaction, nombre: str):
        target = discord.utils.get(interaction.guild.emojis, name=nombre)
        if not target:
            await interaction.response.send_message(
                embed=error_embed(f"No existe un emoji llamado `:{nombre}:` en este servidor."), ephemeral=True
            )
            return

        embed = base_embed(
            f"🆔 ID: `{target.id}`\n"
            f"🎞️ Animado: {'Sí' if target.animated else 'No'}\n"
            f"🕐 Creado: <t:{int(target.created_at.timestamp())}:F>\n"
            f"🔗 [URL]({target.url})",
            COLOR,
            title=f"{target} Información de :{target.name}:",
        )
        embed.set_thumbnail(url=target.url)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmojifulCog(bot))
