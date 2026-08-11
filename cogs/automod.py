from __future__ import annotations
import re
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

import database as db
from utils.sanctions_engine import apply_sanction

INVITE_RE = re.compile(r"(discord\.gg/|discord(app)?\.com/invite/)", re.IGNORECASE)

SPAM_WINDOW = 15   # segundos
SPAM_REPEATS = 4   # mismo mensaje repetido N veces
FLOOD_WINDOW = 8    # segundos
FLOOD_COUNT = 6     # mensajes en ese tiempo
CAPS_MIN_LEN = 10
CAPS_RATIO = 0.7
GHOST_PING_WINDOW = 5  # segundos


class AutoModCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # trackers en memoria (no persisten al reiniciar, es intencional: son ventanas cortas)
        self.recent_messages: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
        self.recent_content: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
        self.ping_cache: dict[int, tuple[float, bool]] = {}  # message_id -> (timestamp, had_mentions)

    async def _enabled(self, guild_id: int) -> bool:
        config = await db.get_guild_config(guild_id)
        return bool(config["automod_enabled"])

    async def _sanction(self, message: discord.Message, key: str, reason: str):
        member = message.guild.get_member(message.author.id)
        if member is None:
            return
        try:
            await apply_sanction(message.guild, member, key, self.bot.user.id, reason)
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not await self._enabled(message.guild.id):
            return
        if message.author.guild_permissions.moderate_members:
            return  # no aplicar automod a Staff

        now = time.time()
        user_id = message.author.id

        # --- Flood ---
        self.recent_messages[user_id].append(now)
        recent = [t for t in self.recent_messages[user_id] if now - t <= FLOOD_WINDOW]
        if len(recent) >= FLOOD_COUNT:
            self.recent_messages[user_id].clear()
            await self._sanction(message, "flood", "Detectado por AutoMod: flood de mensajes")
            return

        # --- Spam (mismo contenido repetido) ---
        if message.content:
            self.recent_content[user_id].append((message.content, now))
            same = [c for c, t in self.recent_content[user_id] if c == message.content and now - t <= SPAM_WINDOW]
            if len(same) >= SPAM_REPEATS:
                self.recent_content[user_id].clear()
                await self._sanction(message, "spam", "Detectado por AutoMod: mensaje repetido")
                return

        # --- Publicidad (invites de Discord) ---
        if INVITE_RE.search(message.content or ""):
            await self._sanction(message, "publicidad", "Detectado por AutoMod: enlace de invitación")
            return

        # --- Mayúsculas excesivas ---
        letters = [c for c in message.content if c.isalpha()]
        if len(letters) >= CAPS_MIN_LEN:
            upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if upper_ratio >= CAPS_RATIO:
                await self._sanction(message, "mayusculas", "Detectado por AutoMod: uso excesivo de mayúsculas")
                return

        # --- Ghost ping tracking ---
        if message.mentions:
            self.ping_cache[message.id] = (now, True)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not await self._enabled(message.guild.id):
            return

        cached = self.ping_cache.pop(message.id, None)
        if not cached:
            return
        posted_at, had_mentions = cached
        if had_mentions and (time.time() - posted_at) <= GHOST_PING_WINDOW:
            member = message.guild.get_member(message.author.id)
            if member and not member.guild_permissions.moderate_members:
                await self._sanction(message, "ghost_ping", "Detectado por AutoMod: ghost ping")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoModCog(bot))
