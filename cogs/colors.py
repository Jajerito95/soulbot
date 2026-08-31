from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands
from database import get_guild_config, update_guild_config
from utils.embeds import success_embed, error_embed

COLORS = [
    ("Rosa", "#FF8FAB", "🌸"),
    ("Rojo", "#E74C3C", "❤️"),
    ("Naranja", "#E67E22", "🧡"),
    ("Amarillo", "#F1C40F", "💛"),
    ("Verde", "#2ECC71", "💚"),
    ("Menta", "#1ABC9C", "🩵"),
    ("Azul", "#3498DB", "💙"),
    ("Violeta", "#9B59B6", "💜"),
    ("Lila", "#A78BFA", "🔮"),
    ("Blanco", "#ECF0F1", "🤍"),
    ("Gris", "#95A5A6", "🩶"),
    ("Negro", "#2C3E50", "🖤"),
]

def _color_name(n: str) -> str: return f"Color {n}"

async def ensure_color_roles(guild: discord.Guild):
    me_top = guild.me.top_role
    created = []
    for name, hex_, _ in COLORS:
        role_name = _color_name(name)
        role = discord.utils.get(guild.roles, name=role_name)
        if role is None:
            try:
                role = await guild.create_role(name=role_name, colour=discord.Colour(int(hex_.lstrip("#"), 16)), reason="Panel colores uwu")
                # intenta ponerlo justo debajo del bot para que se vea
                try: await role.edit(position=max(1, me_top.position - 1))
                except: pass
                created.append(role_name)
            except discord.Forbidden:
                pass
    return created

class ColorSelect(discord.ui.Select):
    def __init__(self):
        opts = [discord.SelectOption(label=name, value=name, emoji=emoji, description=f"Color {name}") for name, _, emoji in COLORS]
        super().__init__(placeholder="Elige tu color uwu...", options=opts, min_values=1, max_values=1, custom_id="soulbot:color_select")
    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        # quita todos los colores previos
        to_remove = [r for r in interaction.user.roles if r.name.startswith("Color ")]
        chosen = self.values[0]
        role = discord.utils.get(guild.roles, name=_color_name(chosen))
        if not role:
            await interaction.response.send_message(embed=error_embed(f"Rol {chosen} no existe. Pide a staff que haga /setup colors de nuevo."), ephemeral=True)
            return
        try:
            if to_remove:
                await interaction.user.remove_roles(*to_remove, reason="Cambio color uwu")
            await interaction.user.add_roles(role, reason="Color uwu")
            await interaction.response.send_message(embed=success_embed(f"¡Color cambiado a **{chosen}** {role.mention} uwu!"), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=error_embed("No tengo permisos para darte ese rol (pon mi rol por encima de los colores)."), ephemeral=True)

class ColorPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ColorSelect())
    @discord.ui.button(label="Quitar color", emoji="❌", style=discord.ButtonStyle.secondary, custom_id="soulbot:color_clear")
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        to_remove = [r for r in interaction.user.roles if r.name.startswith("Color ")]
        if not to_remove:
            await interaction.response.send_message(embed=error_embed("No tienes ningún color puesto."), ephemeral=True)
            return
        try:
            await interaction.user.remove_roles(*to_remove, reason="Quitar color")
            await interaction.response.send_message(embed=success_embed("Color quitado uwu"), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=error_embed("No puedo quitarte el rol."), ephemeral=True)

def build_color_embed(guild: discord.Guild) -> discord.Embed:
    emb = discord.Embed(title="🎨 Elige tu color uwu", description="Selecciona tu color de nombre favorito. Solo puedes tener uno a la vez.\n\n*Los colores son roles con color — se verán en tu nombre en la lista.*", color=0xFF8FAB)
    emb.add_field(name="Colores disponibles", value=" ".join(f"{e} **{n}**" for n, _, e in COLORS), inline=False)
    emb.set_footer(text="SoulSeeker™ • Colores")
    if guild.icon: emb.set_thumbnail(url=guild.icon.url)
    return emb

class ColorsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(ColorPanelView())

    @app_commands.command(name="color", description="Elige tu color de nombre uwu")
    async def color(self, interaction: discord.Interaction):
        # atajo para abrir el selector aunque no estés en el canal
        await interaction.response.send_message(embed=build_color_embed(interaction.guild), view=ColorPanelView(), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ColorsCog(bot))
