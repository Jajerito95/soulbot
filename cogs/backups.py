from __future__ import annotations
import json
import os
import datetime

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR, DATA_DIR

BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUPS_DIR, exist_ok=True)


class BackupsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    backup_group = app_commands.Group(
        name="backup",
        description="Copias de seguridad de la configuración del servidor (Staff)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @backup_group.command(name="create", description="Genera una copia de seguridad de la configuración del servidor")
    async def create(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = await db.export_guild_data(interaction.guild_id)
        data["_meta"] = {
            "guild_id": interaction.guild_id,
            "guild_name": interaction.guild.name,
            "created_at": datetime.datetime.utcnow().isoformat(),
            "created_by": interaction.user.id,
        }

        filename = f"backup_{interaction.guild_id}_{int(datetime.datetime.utcnow().timestamp())}.json"
        path = os.path.join(BACKUPS_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        embed = success_embed(
            "Incluye: configuración general, canales asignados, recompensas de nivel y artículos de la tienda.\n"
            "⚠️ No incluye historial de sanciones, tickets ni sugerencias (eso es un registro, no configuración).",
            title="💾 Backup generado",
        )
        await interaction.followup.send(embed=embed, file=discord.File(path))

    @backup_group.command(name="restore", description="Restaura una copia de seguridad (SOBREESCRIBE la configuración actual)")
    @app_commands.describe(archivo="El archivo .json generado por /backup create", confirmar="Escribe CONFIRMAR para continuar")
    async def restore(self, interaction: discord.Interaction, archivo: discord.Attachment, confirmar: str):
        if confirmar.strip().upper() != "CONFIRMAR":
            await interaction.response.send_message(
                embed=error_embed("Debes escribir exactamente `CONFIRMAR` en el parámetro `confirmar` para continuar. Nada se ha tocado."),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            raw = await archivo.read()
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            await interaction.followup.send(embed=error_embed("Ese archivo no es un backup válido de SoulBot."))
            return

        if "guild_config" not in data:
            await interaction.followup.send(embed=error_embed("Ese archivo no es un backup válido de SoulBot."))
            return

        await db.import_guild_data(interaction.guild_id, data)

        meta = data.get("_meta", {})
        origen = meta.get("guild_name", "desconocido")
        fecha = meta.get("created_at", "desconocida")

        await interaction.followup.send(
            embed=success_embed(
                f"Configuración restaurada.\n📦 Backup original de: **{origen}**\n🕐 Generado: {fecha}",
                title="✅ Backup restaurado",
            )
        )

    @backup_group.command(name="list", description="Lista los backups guardados en este host")
    async def list_backups(self, interaction: discord.Interaction):
        files = sorted(
            [f for f in os.listdir(BACKUPS_DIR) if f.startswith(f"backup_{interaction.guild_id}_")],
            reverse=True,
        )
        if not files:
            await interaction.response.send_message(embed=error_embed("No hay backups guardados en este host todavía."), ephemeral=True)
            return

        lines = []
        for f in files[:10]:
            ts = int(f.split("_")[-1].replace(".json", ""))
            lines.append(f"🗂️ `{f}` — <t:{ts}:f>")

        embed = base_embed(
            "\n".join(lines) + "\n\n⚠️ Estos archivos viven en disco local y **se pierden en cada redeploy** de Render. "
            "Guarda los backups importantes descargándolos de Discord.",
            COLOR,
            title="💾 Backups disponibles",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupsCog(bot))
