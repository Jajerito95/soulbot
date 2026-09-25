from __future__ import annotations
import asyncio
import json
import os
import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR, DATA_DIR

BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUPS_DIR, exist_ok=True)

AUTO_KEEP = 5  # snapshots automáticos a conservar por servidor


class BackupsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_snapshot.start()

    def cog_unload(self):
        self.auto_snapshot.cancel()

    @tasks.loop(hours=6)
    async def auto_snapshot(self):
        """Snapshot automático de niveles/coins/etc. a disco (en Orihost persiste)."""
        for guild in self.bot.guilds:
            try:
                data = await db.export_user_data(guild.id)
                data["_meta"] = {
                    "kind": "auto_users",
                    "guild_id": guild.id,
                    "guild_name": guild.name,
                    "created_at": datetime.datetime.utcnow().isoformat(),
                }
                filename = f"auto_users_{guild.id}_{int(datetime.datetime.utcnow().timestamp())}.json"
                path = os.path.join(BACKUPS_DIR, filename)

                def _write(p=path, d=data):
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(d, f, ensure_ascii=False)

                await asyncio.to_thread(_write)

                def _prune(gid=guild.id):
                    files = sorted(f for f in os.listdir(BACKUPS_DIR) if f.startswith(f"auto_users_{gid}_"))
                    for old in files[:-AUTO_KEEP]:
                        try:
                            os.remove(os.path.join(BACKUPS_DIR, old))
                        except Exception:
                            pass

                await asyncio.to_thread(_prune)
            except Exception:
                pass

    @auto_snapshot.before_loop
    async def _auto_before(self):
        await self.bot.wait_until_ready()

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
        def _write_backup():
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        await asyncio.to_thread(_write_backup)

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

    @backup_group.command(name="restore_users", description="Restaura niveles/coins desde un snapshot (SOBREESCRIBE datos de usuarios)")
    @app_commands.describe(archivo="Archivo auto_users_*.json o manual", confirmar="Escribe CONFIRMAR para continuar")
    async def restore_users(self, interaction: discord.Interaction, archivo: discord.Attachment, confirmar: str):
        if confirmar.strip().upper() != "CONFIRMAR":
            await interaction.response.send_message(
                embed=error_embed("Debes escribir exactamente `CONFIRMAR`. Nada se ha tocado."),
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            raw = await archivo.read()
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            await interaction.followup.send(embed=error_embed("Ese archivo no es un snapshot válido."))
            return

        if "levels" not in data or "economy" not in data:
            await interaction.followup.send(embed=error_embed("Ese archivo no es un snapshot de usuarios (falta levels/economy)."))
            return

        await db.import_user_data(interaction.guild_id, data)
        meta = data.get("_meta", {})
        await interaction.followup.send(
            embed=success_embed(
                f"Niveles, coins, rachas y misiones restaurados.\n🕐 Snapshot de: {meta.get('created_at', 'desconocida')}",
                title="✅ Usuarios restaurados",
            )
        )

    @backup_group.command(name="list", description="Lista los backups guardados en este host")
    async def list_backups(self, interaction: discord.Interaction):
        def _list_backups():
            return sorted(
                [f for f in os.listdir(BACKUPS_DIR) if f.startswith(f"backup_{interaction.guild_id}_")],
                reverse=True,
            )
        files = await asyncio.to_thread(_list_backups)
        if not files:
            await interaction.response.send_message(embed=error_embed("No hay backups guardados en este host todavía."), ephemeral=True)
            return

        lines = []
        for f in files[:10]:
            ts = int(f.split("_")[-1].replace(".json", ""))
            lines.append(f"🗂️ `{f}` — <t:{ts}:f>")

        embed = base_embed(
            "\n".join(lines) + "\n\n⚠️ Viven en el disco del host (en Orihost persiste entre reinicios). "
            "Descarga los importantes de todas formas.",
            COLOR,
            title="💾 Backups disponibles",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupsCog(bot))
