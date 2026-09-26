from __future__ import annotations
import asyncio
import re
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands, tasks

import database as db
from utils.sanctions_engine import apply_sanction
from utils.embeds import warning_embed

INVITE_RE = re.compile(r"(discord\.gg/|discord(app)?\.com/invite/)", re.IGNORECASE)

SPAM_WINDOW = 20
SPAM_REPEATS = 6
FLOOD_WINDOW = 10
FLOOD_COUNT = 8
CAPS_MIN_LEN = 15
CAPS_RATIO = 0.8
GHOST_PING_WINDOW = 5

def _prune_old(dq, now: float, window: float) -> bool:
    """Quita entradas viejas del deque. Devuelve True si quedó vacío."""
    while dq:
        oldest = dq[0]
        ts = oldest[1] if isinstance(oldest, tuple) else oldest
        if now - ts <= window:
            break
        dq.popleft()
    return not dq


# categoría interna -> (columna de config, clave de infracción del catálogo, nombre legible)
CATEGORIES = {
    "spam": ("automod_spam", "spam", "Spam"),
    "flood": ("automod_flood", "flood", "Flood"),
    "caps": ("automod_caps", "mayusculas", "Mayúsculas excesivas"),
    "ghostping": ("automod_ghostping", "ghost_ping", "Ghost Ping"),
    "ads": ("automod_ads", "publicidad", "Publicidad"),
}


class AutoModCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.recent_messages: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
        self.recent_content: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
        self.ping_cache: dict[int, tuple[float, bool]] = {}
        self._cache_cleanup.start()

    def cog_unload(self):
        self._cache_cleanup.cancel()

    @tasks.loop(minutes=1)
    async def _cache_cleanup(self):
        now = time.time()
        cutoff = now - 10
        for mid in [mid for mid, (ts, _) in self.ping_cache.items() if ts < cutoff]:
            del self.ping_cache[mid]
        # purga usuarios inactivos de los deques (las keys externas nunca se borraban)
        for store, window in ((self.recent_messages, FLOOD_WINDOW), (self.recent_content, SPAM_WINDOW)):
            for uid in [uid for uid, dq in store.items() if _prune_old(dq, now, window)]:
                store.pop(uid, None)

    async def _category_enabled(self, guild_id: int, category: str) -> bool:
        config = await db.get_guild_config(guild_id)
        if not config["automod_enabled"]:
            return False
        column = CATEGORIES[category][0]
        return bool(config[column])

    async def _trigger(self, message: discord.Message, category: str, reason: str):
        """
        Aplica el sistema de aviso escalonado: las primeras N veces (configurable)
        solo se avisa por DM sin dejar sanción formal; a partir de ahí, se aplica
        la sanción real del catálogo y el contador de avisos se reinicia.
        """
        member = message.guild.get_member(message.author.id)
        if member is None:
            return

        config = await db.get_guild_config(message.guild.id)
        threshold = config["automod_warn_threshold"]
        _, infraction_key, label = CATEGORIES[category]

        warnings = await db.increment_automod_warning(message.guild.id, member.id, category)

        if warnings <= threshold:
            try:
                await member.send(
                    embed=warning_embed(
                        f"Se detectó **{label.lower()}** en **{message.guild.name}**.\n"
                        f"Este es un aviso ({warnings}/{threshold}). Si continúa, se aplicará una sanción formal.",
                        title="⚠️ Aviso de AutoMod",
                    )
                )
            except discord.Forbidden:
                pass
            return

        # Se superó el umbral de avisos: sanción real + reinicio del contador
        await db.reset_automod_warning(message.guild.id, member.id, category)
        try:
            await apply_sanction(message.guild, member, infraction_key, self.bot.user.id, reason)
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.moderate_members:
            return

        now = time.time()
        user_id = message.author.id
        content = message.content or ""

        # 1 sola query (con caché de 45s) en vez de 5
        config = await db.get_guild_config(message.guild.id)
        if not config["automod_enabled"]:
            return

        if config[CATEGORIES["flood"][0]]:
            dq = self.recent_messages[user_id]
            dq.append(now)
            _prune_old(dq, now, FLOOD_WINDOW)
            if len(dq) >= FLOOD_COUNT:
                dq.clear()
                await self._trigger(message, "flood", "Detectado por AutoMod: flood de mensajes")
                return

        if config[CATEGORIES["spam"][0]] and content:
            dq = self.recent_content[user_id]
            dq.append((content, now))
            _prune_old(dq, now, SPAM_WINDOW)
            same = sum(1 for c, _ in dq if c == content)
            if same >= SPAM_REPEATS:
                dq.clear()
                await self._trigger(message, "spam", "Detectado por AutoMod: mensaje repetido")
                return

        if config[CATEGORIES["ads"][0]] and "discord" in content.lower() and INVITE_RE.search(content):
            await self._trigger(message, "ads", "Detectado por AutoMod: enlace de invitación")
            return

        if config[CATEGORIES["caps"][0]] and len(content) >= CAPS_MIN_LEN:
            # 1 sola pasada, sin crear lista
            letters = upper = 0
            for c in content:
                if c.isalpha():
                    letters += 1
                    if c.isupper():
                        upper += 1
            if letters >= CAPS_MIN_LEN and upper / letters >= CAPS_RATIO:
                await self._trigger(message, "caps", "Detectado por AutoMod: uso excesivo de mayúsculas")
                return

        if message.mentions:
            self.ping_cache[message.id] = (now, True)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not await self._category_enabled(message.guild.id, "ghostping"):
            return

        cached = self.ping_cache.pop(message.id, None)
        if not cached:
            return
        posted_at, had_mentions = cached
        if had_mentions and (time.time() - posted_at) <= GHOST_PING_WINDOW:
            member = message.guild.get_member(message.author.id)
            if member and not member.guild_permissions.moderate_members:
                await self._trigger(message, "ghostping", "Detectado por AutoMod: ghost ping")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoModCog(bot))
