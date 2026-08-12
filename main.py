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

COGS = ["cogs.embed", "cogs.welcome", "cogs.suggestions", "cogs.tickets", "cogs.setup", "cogs.logs", "cogs.test", "cogs.emojiful", "cogs.purge", "cogs.sanction", "cogs.automod", "cogs.levels"]


class SoulBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        await init_db()
        for cog in COGS:
            await self.load_extension(cog)
            log.info(f"Cog cargado: {cog}")
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(f"Comandos slash sincronizados al instante en el servidor {GUILD_ID}.")
        else:
            await self.tree.sync()
            log.info("Comandos slash sincronizados globalmente (puede tardar hasta 1h en propagarse).")


bot = SoulBot()


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
