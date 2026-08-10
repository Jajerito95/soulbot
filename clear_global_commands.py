"""
Ejecuta esto UNA sola vez para borrar los comandos slash GLOBALES
(los duplicados que quedaron de antes de usar GUILD_ID).
Los comandos de tu servidor (guild) no se tocan.

Uso:
    python clear_global_commands.py
"""
import asyncio
import discord
from config import TOKEN


async def main():
    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        client.tree.clear_commands(guild=None)  # limpia solo las globales
        await client.tree.sync()  # sincroniza el "vacío" global
        print("✅ Comandos globales borrados. Los de tu servidor (guild) siguen intactos.")
        await client.close()

    client.tree = discord.app_commands.CommandTree(client)
    await client.start(TOKEN)


asyncio.run(main())
