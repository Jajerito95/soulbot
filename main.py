from __future__ import annotations
import logging

import discord
from discord.ext import commands

from config import TOKEN, GUILD_ID
from database import init_db
from keep_alive import keep_alive

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
log = logging.getLogger("soulbot")

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.presences = True

COGS = ["cogs.embed", "cogs.welcome", "cogs.suggestions", "cogs.tickets", "cogs.setup", "cogs.logs", "cogs.test", "cogs.emojiful", "cogs.purge", "cogs.sanction", "cogs.automod", "cogs.levels", "cogs.economy", "cogs.minigames", "cogs.boardgames", "cogs.appeals", "cogs.backups", "cogs.temproles", "cogs.maintenance", "cogs.code_sync", "cogs.colors", "cogs.vc_tts", "cogs.giveaways", "cogs.missions", "cogs.relampago", "cogs.streaks", "cogs.boss"]


class SoulBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        await init_db()
        import database
        if database.USING_TURSO:
            log.info("DB: Turso (nube, persistente entre reinicios de Render).")
        else:
            log.warning("DB: SQLite LOCAL (se PIERDE en cada redeploy de Render Free). "
                        "Define TURSO_DATABASE_URL y TURSO_AUTH_TOKEN para no perder datos.")
        # Seguridad: advierte si RCON es público
        try:
            from config import RCON_HOST
            if RCON_HOST and ("bore.pub" in RCON_HOST or "trycloudflare" in RCON_HOST):
                log.warning("RCON usa túnel público bore.pub — cambia a Tailscale 100.x.x.x para cifrado.")
        except Exception:
            pass
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(f"Cog cargado: {cog}")
            except Exception as e:
                log.exception(f"Fallo al cargar {cog}: {e} — el bot sigue sin ese módulo")
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(f"Comandos slash sincronizados al instante en el servidor {GUILD_ID}.")
        else:
            await self.tree.sync()
            log.info("Comandos slash sincronizados globalmente (puede tardar hasta 1h en propagarse).")


bot = SoulBot()

import discord.app_commands as app_commands
from utils.embeds import error_embed as _err_embed

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    # Interacción caducada (10062) — latencia, la ignoramos
    if isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, discord.NotFound):
        return
    # Permisos faltantes
    orig = error.original if isinstance(error, app_commands.CommandInvokeError) else error
    if isinstance(orig, discord.Forbidden):
        log.warning(f"Permisos insuficientes en {interaction.command}: {orig}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=_err_embed("Sin permisos", "No tengo permisos para hacer eso. Revisa mis permisos y jerarquía."), ephemeral=True)
            else:
                await interaction.followup.send(embed=_err_embed("Sin permisos", "No tengo permisos para hacer eso."), ephemeral=True)
        except Exception:
            pass
        return
    if isinstance(orig, app_commands.CheckFailure):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=_err_embed("No autorizado", "No tienes permisos para usar este comando."), ephemeral=True)
            else:
                await interaction.followup.send(embed=_err_embed("No autorizado", "No tienes permisos."), ephemeral=True)
        except Exception:
            pass
        return
    if isinstance(orig, app_commands.CommandOnCooldown):
        try:
            await interaction.response.send_message(embed=_err_embed("Cooldown", f"Espera {orig.retry_after:.1f}s antes de reutilizar."), ephemeral=True)
        except Exception:
            pass
        return
    # Cooldown genérico y otros
    # Para cualquier error no manejado, notifica al usuario sin crashear el bot
    log.exception("Error en comando slash %s: %s", getattr(interaction.command, 'name', '?'), error)
    try:
        msg = f"```{str(orig)[:400]}```" if orig else f"```{str(error)[:400]}```"
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=_err_embed("Error interno", f"Ocurrió un error inesperado.\n{msg}"), ephemeral=True)
        else:
            await interaction.followup.send(embed=_err_embed("Error interno", f"Ocurrió un error.\n{msg}"), ephemeral=True)
    except Exception:
        pass

# Anti-crash global: captura excepciones no manejadas en tasks
import asyncio
def _handle_task_exception(loop, context):
    msg = context.get("exception")
    log.error(f"Task exception: {msg} — {context.get('message')}")

try:
    asyncio.get_event_loop().set_exception_handler(_handle_task_exception)
except RuntimeError:
    pass


@bot.event
async def on_ready():
    log.info(f"✅ SoulBot conectado como {bot.user} ({bot.user.id})")
    from utils.embeds import set_footer_icon
    set_footer_icon(bot.user.display_avatar.url)
    await bot.change_presence(activity=discord.Game(name="SoulSeeker™"))


def main():
    if not TOKEN:
        raise RuntimeError("❌ No se encontró DISCORD_TOKEN en las variables de entorno.")
    keep_alive()
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
