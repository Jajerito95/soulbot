from __future__ import annotations
"""Vigilante de Turso: ping cada 5 min, avisa si cae y cuando vuelve."""
import asyncio
import os
import time

from discord.ext import commands, tasks

import database as db
from config import DATA_DIR

RENEW_EVERY_DAYS = 3  # avisa cada 3 días para renovar el server en el panel
RENEW_MARKER = os.path.join(DATA_DIR, "last_renew_reminder.txt")

RAM_PURGE_MB = 420  # si la RAM pasa de esto, purga cachés y avisa (Orihost mata en ~512)


def _rss_mb() -> int | None:
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    except Exception:
        return None


class DbWatchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fails = 0
        self.down = False
        self.last_error = ""
        self.rss_mb: int | None = None
        self._log_channels: dict[int, int] = {}  # guild_id -> logs_channel_id (caché para alertar sin DB)
        self.watch.start()
        self.renew_reminder.start()

    def cog_unload(self):
        self.watch.cancel()
        self.renew_reminder.cancel()

    def _renew_due(self) -> bool:
        try:
            with open(RENEW_MARKER, encoding="utf-8") as f:
                last = float(f.read().strip())
            return (time.time() - last) >= RENEW_EVERY_DAYS * 86400
        except Exception:
            return True

    def _renew_mark(self):
        try:
            os.makedirs(os.path.dirname(RENEW_MARKER), exist_ok=True)
            with open(RENEW_MARKER, "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except Exception:
            pass

    @tasks.loop(hours=24)
    async def renew_reminder(self):
        if not self._renew_due():
            return
        delivered = await self._alert(
            f"🔔 **Recordatorio:** renueva el servidor en el panel de Orihost "
            f"(cada ~{RENEW_EVERY_DAYS} días) para que SoulBot no se apague. "
            f"Panel → tu server → Renew. Tras renovar no hay que hacer nada más."
        )
        if delivered:
            self._renew_mark()

    @renew_reminder.before_loop
    async def _renew_before(self):
        await self.bot.wait_until_ready()

    async def _ping(self) -> tuple[bool, int | None]:
        try:
            t = time.perf_counter()
            cur = await db.db().execute("SELECT 1")
            await cur.fetchone()
            return True, round((time.perf_counter() - t) * 1000)
        except Exception as e:
            self.last_error = str(e)[:200]
            return False, None

    async def _alert(self, text: str) -> bool:
        """Avisa por consola + canal de logs. No usa la DB (puede estar caída). Devuelve si llegó a algún canal."""
        import discord
        print(f"[dbwatch] {text}", flush=True)
        delivered = False
        for guild in self.bot.guilds:
            try:
                ch_id = self._log_channels.get(guild.id)
                if ch_id is None:
                    try:
                        cfg = await db.get_guild_config(guild.id)
                        ch_id = cfg.get("logs_channel_id")
                        if ch_id:
                            self._log_channels[guild.id] = ch_id
                    except Exception:
                        ch_id = None
                if not ch_id:
                    continue
                ch = guild.get_channel(ch_id)
                if ch is None:
                    try:
                        ch = await guild.fetch_channel(ch_id)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        ch = None
                if ch:
                    await ch.send(text)
                    delivered = True
            except Exception:
                pass
        return delivered

    @tasks.loop(minutes=5)
    async def watch(self):
        if not db.USING_TURSO:
            return
        ok, _ = await self._ping()
        # vigilante de RAM: confirma si las caídas son por memoria y purga antes del OOM-kill
        self.rss_mb = await asyncio.to_thread(_rss_mb)
        if self.rss_mb and self.rss_mb >= RAM_PURGE_MB:
            try:
                from utils.card_renderer import _avatar_cache
                _avatar_cache.clear()
            except Exception:
                pass
            await asyncio.to_thread(__import__("gc").collect)
            after = await asyncio.to_thread(_rss_mb)
            print(f"[dbwatch] ⚠️ RAM alta: {self.rss_mb}MB → purga → {after}MB", flush=True)
            self.rss_mb = after
        if ok:
            # mantiene caliente la caché de canales de logs (barato: get_guild_config cachea 45s)
            for guild in self.bot.guilds:
                try:
                    cfg = await db.get_guild_config(guild.id)
                    if cfg.get("logs_channel_id"):
                        self._log_channels[guild.id] = cfg["logs_channel_id"]
                except Exception:
                    pass
            if self.down:
                self.down = False
                self.fails = 0
                await self._alert("✅ Turso volvió a responder.")
        else:
            self.fails += 1
            if self.fails >= 2 and not self.down:
                self.down = True
                await self._alert(
                    "🚨 **Turso no responde** (2 fallos seguidos). "
                    "Los datos nuevos pueden perderse. Hay snapshots en `/backup list` y `snapshot` en consola."
                )

    @watch.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(DbWatchCog(bot))
