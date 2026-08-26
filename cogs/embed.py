from __future__ import annotations
from typing import Optional
import re

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.embeds import error_embed

HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def _parse_hex(value: str) -> Optional[int]:
    if not HEX_RE.match(value.strip()):
        return None
    return int(value.strip().lstrip("#"), 16)


class ContentModal(discord.ui.Modal, title="Contenido del embed"):
    def __init__(self, view: "EmbedBuilderView"):
        super().__init__()
        self.view_ref = view
        self.title_input = discord.ui.TextInput(
            label="Título (opcional)", required=False, max_length=256,
            default=view.embed.title or "",
        )
        self.desc_input = discord.ui.TextInput(
            label="Descripción", style=discord.TextStyle.paragraph, required=False, max_length=4000,
            default=view.embed.description or "",
        )
        self.add_item(self.title_input)
        self.add_item(self.desc_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.embed.title = self.title_input.value or None
        self.view_ref.embed.description = self.desc_input.value or None
        await self.view_ref.refresh(interaction)


class ColorModal(discord.ui.Modal, title="Color del embed"):
    color_input = discord.ui.TextInput(label="HEX (ej: #5865F2)", max_length=7, required=True)

    def __init__(self, view: "EmbedBuilderView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        parsed = _parse_hex(self.color_input.value)
        if parsed is None:
            await interaction.response.send_message(embed=error_embed(f"`{self.color_input.value}` no es un HEX válido."), ephemeral=True)
            return
        self.view_ref.embed.color = parsed
        await self.view_ref.refresh(interaction)


class FooterModal(discord.ui.Modal, title="Footer"):
    def __init__(self, view: "EmbedBuilderView"):
        super().__init__()
        self.view_ref = view
        self.text_input = discord.ui.TextInput(
            label="Texto del footer", required=False, max_length=2048,
            default=(view.embed.footer.text or "") if view.embed.footer else "",
        )
        self.icon_input = discord.ui.TextInput(
            label="URL del icono (opcional)", required=False,
            default=(view.embed.footer.icon_url or "") if view.embed.footer else "",
        )
        self.add_item(self.text_input)
        self.add_item(self.icon_input)

    async def on_submit(self, interaction: discord.Interaction):
        if self.text_input.value:
            self.view_ref.embed.set_footer(text=self.text_input.value, icon_url=self.icon_input.value or None)
        else:
            self.view_ref.embed.remove_footer()
        await self.view_ref.refresh(interaction)


class AuthorModal(discord.ui.Modal, title="Autor"):
    def __init__(self, view: "EmbedBuilderView"):
        super().__init__()
        self.view_ref = view
        self.name_input = discord.ui.TextInput(
            label="Nombre del autor", required=False, max_length=256,
            default=(view.embed.author.name or "") if view.embed.author else "",
        )
        self.icon_input = discord.ui.TextInput(
            label="URL del icono (opcional)", required=False,
            default=(view.embed.author.icon_url or "") if view.embed.author else "",
        )
        self.add_item(self.name_input)
        self.add_item(self.icon_input)

    async def on_submit(self, interaction: discord.Interaction):
        if self.name_input.value:
            self.view_ref.embed.set_author(name=self.name_input.value, icon_url=self.icon_input.value or None)
        else:
            self.view_ref.embed.remove_author()
        await self.view_ref.refresh(interaction)


class ImagesModal(discord.ui.Modal, title="Imágenes"):
    def __init__(self, view: "EmbedBuilderView"):
        super().__init__()
        self.view_ref = view
        self.thumb_input = discord.ui.TextInput(
            label="URL del thumbnail (esquina)", required=False,
            default=(view.embed.thumbnail.url or "") if view.embed.thumbnail else "",
        )
        self.image_input = discord.ui.TextInput(
            label="URL de la imagen grande", required=False,
            default=(view.embed.image.url or "") if view.embed.image else "",
        )
        self.add_item(self.thumb_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.embed.set_thumbnail(url=self.thumb_input.value or None)
        self.view_ref.embed.set_image(url=self.image_input.value or None)
        await self.view_ref.refresh(interaction)


class AddFieldModal(discord.ui.Modal, title="Añadir campo"):
    name_input = discord.ui.TextInput(label="Nombre del campo", max_length=256)
    value_input = discord.ui.TextInput(label="Valor del campo", style=discord.TextStyle.paragraph, max_length=1024)
    inline_input = discord.ui.TextInput(label="¿En línea? (si/no)", default="no", max_length=3)

    def __init__(self, view: "EmbedBuilderView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        if len(self.view_ref.embed.fields) >= 25:
            await interaction.response.send_message(embed=error_embed("Máximo 25 campos por embed."), ephemeral=True)
            return
        inline = self.inline_input.value.strip().lower() in ("si", "sí", "yes", "true")
        self.view_ref.embed.add_field(name=self.name_input.value, value=self.value_input.value, inline=inline)
        await self.view_ref.refresh(interaction, rebuild=True)


class RemoveFieldSelect(discord.ui.Select):
    def __init__(self, view: "EmbedBuilderView"):
        options = [
            discord.SelectOption(label=f"#{i+1} — {f.name[:80]}", value=str(i))
            for i, f in enumerate(view.embed.fields)
        ]
        super().__init__(placeholder="Elige un campo a eliminar...", options=options, row=3)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        self.view_ref.embed.remove_field(index)
        await self.view_ref.refresh(interaction, rebuild=True)


class EmbedBuilderView(discord.ui.View):
    def __init__(self, author_id: int, target_channel: discord.TextChannel):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.target_channel = target_channel
        self.embed = discord.Embed(description="*Empieza a editar con los botones de abajo...*", color=config.COLOR)
        self._rebuild_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("Este builder no es tuyo."), ephemeral=True)
            return False
        return True

    async def refresh(self, interaction: discord.Interaction, rebuild: bool = False):
        if rebuild:
            self._rebuild_components()
        await interaction.response.edit_message(embed=self.embed, view=self)

    def _rebuild_components(self):
        self.clear_items()
        self.add_item(_ContentButton())
        self.add_item(_ColorButton())
        self.add_item(_FooterButton())
        self.add_item(_AuthorButton())
        self.add_item(_ImagesButton())
        self.add_item(_AddFieldButton())
        self.add_item(_SendButton())
        self.add_item(_CancelButton())
        if self.embed.fields:
            self.add_item(RemoveFieldSelect(self))


class _ContentButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Contenido", emoji="📝", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ContentModal(self.view))


class _ColorButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Color", emoji="🎨", style=discord.ButtonStyle.secondary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ColorModal(self.view))


class _FooterButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Footer", emoji="🔻", style=discord.ButtonStyle.secondary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(FooterModal(self.view))


class _AuthorButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Autor", emoji="👤", style=discord.ButtonStyle.secondary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AuthorModal(self.view))


class _ImagesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Imágenes", emoji="🖼️", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ImagesModal(self.view))


class _AddFieldButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Añadir campo", emoji="➕", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddFieldModal(self.view))


class _SendButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Enviar", emoji="✅", style=discord.ButtonStyle.success, row=2)

    async def callback(self, interaction: discord.Interaction):
        view: EmbedBuilderView = self.view
        if not view.embed.description and not view.embed.title and not view.embed.fields:
            await interaction.response.send_message(embed=error_embed("El embed está vacío."), ephemeral=True)
            return
        await view.target_channel.send(embed=view.embed)
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Embed enviado a {view.target_channel.mention}.", embed=view.embed, view=view
        )
        view.stop()


class _CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancelar", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)

    async def callback(self, interaction: discord.Interaction):
        for child in self.view.children:
            child.disabled = True
        await interaction.response.edit_message(content="❌ Cancelado.", embed=None, view=self.view)
        self.view.stop()


class EmbedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="embed", description="Abre el builder avanzado de embeds con vista previa en vivo")
    @app_commands.describe(canal="Canal donde se enviará el embed (por defecto, este mismo)")
    async def embed(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
        target = canal or interaction.channel
        view = EmbedBuilderView(interaction.user.id, target)
        await interaction.response.send_message(
            content=f"🧩 **Embed Builder** — se enviará a {target.mention}. Usa los botones, la vista previa se actualiza al instante.",
            embed=view.embed, view=view, ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedCog(bot))
