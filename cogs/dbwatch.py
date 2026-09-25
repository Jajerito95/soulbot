from __future__ import annotations
"""Vigilante de Turso: ping cada 5 min, avisa si cae y cuando vuelve."""
import time

from discord.ext import commands, tasks

import database as db


class DbWatchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fails = 0
        self.down = False
        self.last_error = ""
        self.watch.start()

    def cog_unload(self):
        self.watch.cancel()

    async def _ping(self) -> tuple[bool, int | None]:
        try:
            t = time.perf_counter()
            cur = await db.db().execute("SELECT 1")
            await cur.fetchone()
            return True, round((time.perf_counter() - t) * 1000)
        except Exception as e:
            self.last_error = str(e)[:200]
            return False, None

    async def _alert(self, text: str):
        print(f"[dbwatch] {text}", flush=True)
        for guild in self.bot.guilds:
            try:
                cfg = await db.get_guild_config(guild.id)
                ch_id = cfg.get("logs_channel_id")
                if ch_id and (ch := guild.get_channel(ch_id)):
                    await ch.send(text)
            except Exception:
                pass

    @tasks.loop(minutes=5)
    async def watch(self):
        if not db.USING_TURSO:
            return
        ok, _ = await self._ping()
        if ok:
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
