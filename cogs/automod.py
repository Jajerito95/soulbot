from __future__ import annotations
import re
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

import database as db
from utils.sanctions_engine import apply_sanction
from utils.embeds import warning_embed

INVITE_RE = re.compile(r"(discord\.gg/|discord(app)?\.com/invite/)", re.IGNORECASE)

SPAM_WINDOW = 15
SPAM_REPEATS = 4
FLOOD_WINDOW = 8
FLOOD_COUNT = 6
CAPS_MIN_LEN = 10
CAPS_RATIO = 0.7
GHOST_PING_WINDOW = 5

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

        if await self._category_enabled(message.guild.id, "flood"):
            self.recent_messages[user_id].append(now)
            recent = [t for t in self.recent_messages[user_id] if now - t <= FLOOD_WINDOW]
            if len(recent) >= FLOOD_COUNT:
                self.recent_messages[user_id].clear()
                await self._trigger(message, "flood", "Detectado por AutoMod: flood de mensajes")
                return

        if await self._category_enabled(message.guild.id, "spam") and message.content:
            self.recent_content[user_id].append((message.content, now))
            same = [c for c, t in self.recent_content[user_id] if c == message.content and now - t <= SPAM_WINDOW]
            if len(same) >= SPAM_REPEATS:
                self.recent_content[user_id].clear()
                await self._trigger(message, "spam", "Detectado por AutoMod: mensaje repetido")
                return

        if await self._category_enabled(message.guild.id, "ads") and INVITE_RE.search(message.content or ""):
            await self._trigger(message, "ads", "Detectado por AutoMod: enlace de invitación")
            return

        if await self._category_enabled(message.guild.id, "caps"):
            letters = [c for c in message.content if c.isalpha()]
            if len(letters) >= CAPS_MIN_LEN:
                upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
                if upper_ratio >= CAPS_RATIO:
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
