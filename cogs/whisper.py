from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

WHISPER_LOG_CHANNEL_ID = 1517597549760872489  # canal staff privado para logs de whisper


class WhisperCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="whisper", description="Envía un mensaje anónimo a alguien (como MC 🤫)")
    @app_commands.describe(usuario="Quién recibe el whisper", mensaje="El mensaje secreto")
    async def whisper(self, interaction: discord.Interaction, usuario: discord.Member, mensaje: str):
        if usuario.id == interaction.user.id:
            await interaction.response.send_message(embed=error_embed("No puedes enviarte un whisper a ti mismo."), ephemeral=True)
            return
        if usuario.bot:
            await interaction.response.send_message(embed=error_embed("No puedes enviar whispers a bots."), ephemeral=True)
            return
        if len(mensaje) > 500:
            await interaction.response.send_message(embed=error_embed("Máximo 500 caracteres."), ephemeral=True)
            return

        # embed privado para el destinatario
        embed_recipient = base_embed(
            f"De **Alguien Anónimo** 🤫:\n\n>>> {mensaje}",
            COLOR, title="📩 Whisper anónimo"
        )
        embed_recipient.set_footer(text="SoulSeeker™ • Whisper • No se puede responder directamente")

        # DM al destinatario
        try:
            await usuario.send(embed=embed_recipient)
            dm_ok = True
        except discord.Forbidden:
            dm_ok = False

        # log al canal staff — SOLO el contenido, NO quién envió
        log_channel = self.bot.get_channel(WHISPER_LOG_CHANNEL_ID)
        if log_channel:
            log_embed = base_embed(
                f"**Para:** {usuario.mention}\n"
                f"**Mensaje:**\n>>> {mensaje}\n\n"
                f"**DM enviado:** {'✅' if dm_ok else '❌ (desactivados)'}",
                COLOR, title="🤫 Whisper (moderación)"
            )
            try:
                await log_channel.send(embed=log_embed)
            except Exception:
                pass

        if dm_ok:
            await interaction.response.send_message(
                embed=success_embed(f"Whisper enviado a {usuario.mention} 🤫\n*Mensaje entregado por DM.*"),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No pude enviar DM a {usuario.mention} (tienen DMs desactivados).\nEl staff puede ver el mensaje en el canal de logs."),
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(WhisperCog(bot))
