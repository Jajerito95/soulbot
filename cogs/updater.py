from __future__ import annotations
"""Actualización en caliente desde GitHub: git pull + reload de cogs, sin reiniciar."""
import asyncio
import os
import shutil
import subprocess
import tempfile
import zipfile
import datetime

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import COLOR, GUILD_ID, GITHUB_REPO, GIT_BRANCH
from utils.embeds import success_embed, error_embed, base_embed

# archivos que al cambiar requieren Restart (no se pueden recargar en caliente)
_RESTART_FILES = {"main.py", "config.py", "keep_alive.py", "Procfile", "requirements.txt"}
_SKIP_DIRS = {".git", "data", "__pycache__", ".venv", "logs", "node_modules"}


def _run_git(args: list[str], timeout: int = 45) -> tuple[int, str]:
    """Ejecuta git de forma síncrona (llamar vía to_thread). Retorna (código, salida)."""
    try:
        proc = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=timeout,
            cwd=os.getcwd(), env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 127, "git no está instalado en el contenedor"
    except subprocess.TimeoutExpired:
        return 124, "timeout ejecutando git"


def _has_git_repo() -> bool:
    code, _ = _run_git(["rev-parse", "--is-inside-work-tree"], timeout=10)
    return code == 0


def _zip_update() -> dict:
    """Fallback sin git: descarga el zip de GitHub y sobreescribe los archivos."""
    repo = (GITHUB_REPO or "").strip()
    if "/" not in repo:
        return {"updated": False, "error": "Sin repo git local y GITHUB_REPO no está definido."}
    import urllib.request
    url = f"https://codeload.github.com/{repo}/zip/refs/heads/{GIT_BRANCH}"
    try:
        with tempfile.TemporaryDirectory() as td:
            zip_path = os.path.join(td, "repo.zip")
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(td)
            root = next(d for d in os.listdir(td) if d.startswith(repo.split("/")[-1]))
            src = os.path.join(td, root)
            changed = []
            for dirpath, dirnames, filenames in os.walk(src):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                rel = os.path.relpath(dirpath, src)
                dst_dir = os.getcwd() if rel == "." else os.path.join(os.getcwd(), rel)
                os.makedirs(dst_dir, exist_ok=True)
                for fn in filenames:
                    if fn == ".env" or "__pycache__" in fn:
                        continue
                    s, d = os.path.join(dirpath, fn), os.path.join(dst_dir, fn)
                    shutil.copy2(s, d)
                    changed.append(os.path.relpath(d, os.getcwd()).replace("\\", "/"))
            return {"updated": True, "files": changed, "mode": "zip"}
    except Exception as e:
        return {"updated": False, "error": f"Descarga zip falló: {e}"}


def _pull_changes() -> dict:
    if not _has_git_repo():
        return _zip_update()
    # por si el repo pertenece a otro usuario en el contenedor (Pterodactyl)
    _run_git(["config", "--global", "--add", "safe.directory", os.getcwd()], timeout=10)
    code, out = _run_git(["fetch", "origin", GIT_BRANCH])
    if code != 0:
        return _zip_update() if code == 127 else {"updated": False, "error": f"git fetch falló: {out[:300]}"}
    code, out = _run_git(["rev-list", "--count", f"HEAD..origin/{GIT_BRANCH}"])
    behind = int(out.strip() or "0") if code == 0 else 0
    if behind == 0:
        return {"updated": False}
    code, out = _run_git(["pull", "--ff-only", "origin", GIT_BRANCH], timeout=120)
    if code != 0:
        return {"updated": False, "error": f"git pull falló (¿cambios locales?): {out[:300]}"}
    code, diff = _run_git(["diff", "--name-only", "ORIG_HEAD", "HEAD"])
    files = [f.strip() for f in diff.splitlines() if f.strip()] if code == 0 else []
    return {"updated": True, "files": files, "mode": "git", "behind": behind}


class UpdaterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._busy = False
        self.started_at = datetime.datetime.now()

    @app_commands.command(name="update", description="Comprueba y aplica actualizaciones desde GitHub sin apagar el bot (Staff)")
    async def update(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(embed=error_embed("Solo Staff."), ephemeral=True)
            return
        if self._busy:
            await interaction.response.send_message(embed=error_embed("Ya hay una actualización en curso."), ephemeral=True)
            return
        self._busy = True
        await interaction.response.defer(ephemeral=True)
        try:
            result = await asyncio.to_thread(_pull_changes)

            if not result.get("updated"):
                if result.get("error"):
                    await interaction.followup.send(embed=error_embed(result["error"], "❌ Update falló"))
                else:
                    await interaction.followup.send(embed=success_embed("Ya estás en la última versión. Nada que actualizar. ✅", "📦 Sin cambios"))
                return

            files = result.get("files", [])
            # 1) migraciones nuevas de DB (init_db es idempotente)
            try:
                await db.init_db()
            except Exception:
                pass
            # 2) recargar todos los cogs cargados
            reloaded, failed = [], []
            for ext in sorted(self.bot.extensions.keys()):
                if ext == "cogs.updater":
                    continue
                try:
                    await self.bot.reload_extension(ext)
                    reloaded.append(ext)
                except Exception as e:
                    failed.append(f"{ext}: {str(e)[:80]}")
            try:
                await self.bot.reload_extension("cogs.updater")
            except Exception:
                pass
            # 3) resincronizar slash commands
            try:
                if GUILD_ID:
                    g = discord.Object(id=GUILD_ID)
                    self.bot.tree.copy_global_to(guild=g)
                    self.bot.tree.clear_commands(guild=None)
                    await self.bot.tree.sync(guild=g)
                else:
                    await self.bot.tree.sync()
            except Exception:
                pass

            needs_restart = any(f.split("/")[0] in _RESTART_FILES for f in files)
            shown = "\n".join(files[:12]) + (f"\n… y {len(files) - 12} más" if len(files) > 12 else "")
            desc = (
                f"📥 {len(files)} archivos actualizados ({result.get('mode', 'git')})\n"
                f"🔄 {len(reloaded)} cogs recargados\n\n```{shown or 'sin detalle'}```"
            )
            if failed:
                desc += f"\n⚠️ Fallos al recargar:\n" + "\n".join(failed[:5])
            if needs_restart:
                desc += "\n🚨 Se tocaron main.py/config/requirements — haz un **Restart** manual para aplicar todo."
            await interaction.followup.send(embed=success_embed(desc, "✅ Bot actualizado"))
        except Exception as e:
            try:
                await interaction.followup.send(embed=error_embed(f"Error inesperado: {str(e)[:300]}", "❌ Update"))
            except Exception:
                pass
        finally:
            self._busy = False

    @app_commands.command(name="version", description="Muestra la versión (commit) actual del bot")
    async def version(self, interaction: discord.Interaction):
        await interaction.response.defer()
        code, out = await asyncio.to_thread(_run_git, ["log", "-1", "--format=%h • %ci • %s"])
        commit = out.strip() if code == 0 else "Sin git (instalación zip)"
        await interaction.followup.send(embed=base_embed(
            f"`{commit}`\n🧠 SoulBot • encendido desde {self.started_at.strftime('%d/%m %H:%M')}",
            COLOR, title="📌 Versión",
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(UpdaterCog(bot))
