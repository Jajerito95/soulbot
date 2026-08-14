from __future__ import annotations
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import success_embed, error_embed


class MaintenanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.enabled = False
        self.reason: Optional[str] = None
        self.bot.tree.interaction_check = self.global_check

    async def global_check(self, interaction: discord.Interaction) -> bool:
        if not self.enabled:
            return True
        if await self.bot.is_owner(interaction.user):
            return True

        desc = "🔧 SoulBot está en mantenimiento ahora mismo. Vuelve a intentarlo en un rato."
        if self.reason:
            desc += f"\n📝 Motivo: {self.reason}"
        await interaction.response.send_message(embed=error_embed(desc, title="🔧 Mantenimiento"), ephemeral=True)
        return False

    maintenance_group = app_commands.Group(name="maintenance", description="Modo mantenimiento del bot (solo dueño)")

    @maintenance_group.command(name="on", description="Activa el modo mantenimiento (bot invisible, comandos bloqueados)")
    @app_commands.describe(razon="Motivo a mostrar a los usuarios (opcional)")
    async def on(self, interaction: discord.Interaction, razon: Optional[str] = None):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message(embed=error_embed("Solo el dueño del bot puede usar esto."), ephemeral=True)
            return

        self.enabled = True
        self.reason = razon
        await self.bot.change_presence(status=discord.Status.invisible)

        await interaction.response.send_message(
            embed=success_embed(
                f"🔧 Modo mantenimiento **activado**.\nEl bot aparece desconectado y ningún comando funcionará excepto para ti."
                + (f"\n📝 Motivo: {razon}" if razon else ""),
            ),
            ephemeral=True,
        )

    @maintenance_group.command(name="off", description="Desactiva el modo mantenimiento")
    async def off(self, interaction: discord.Interaction):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message(embed=error_embed("Solo el dueño del bot puede usar esto."), ephemeral=True)
            return

        self.enabled = False
        self.reason = None
        await self.bot.change_presence(status=discord.Status.online, activity=discord.Game(name="SoulSeeker™"))

        await interaction.response.send_message(embed=success_embed("✅ Modo mantenimiento **desactivado**. Todo vuelve a funcionar con normalidad."), ephemeral=True)

    @maintenance_group.command(name="status", description="Muestra si el modo mantenimiento está activo")
    async def status(self, interaction: discord.Interaction):
        estado = "🔧 Activado" if self.enabled else "✅ Desactivado"
        desc = f"Estado: **{estado}**"
        if self.enabled and self.reason:
            desc += f"\n📝 Motivo: {self.reason}"
        await interaction.response.send_message(embed=success_embed(desc, title="🔧 Modo mantenimiento"), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MaintenanceCog(bot))
