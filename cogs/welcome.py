from __future__ import annotations
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from database import db, get_guild_config
from utils.embeds import success_embed, error_embed, get_footer_icon
from config import BRAND, COLOR

DEFAULT_WELCOME = (
    "🥳 **¡Un nuevo miembro ha emergido!**\n\n"
    "👋 ¡Hola {user}! Bienvenido a **SoulSeeker™ | Oficial**\n\n"
    "Disfruta de tu estadía, pásate por los canales de soporte si necesitas algo "
    "y sé bienvenido a nuestra comunidad.\n\n"
    "👥 **Miembros totales:** `{member_count}`"
)


def build_welcome_embed(member: discord.Member, template: str) -> discord.Embed:
    text = template.format(
        mention=member.mention,
        user=member.display_name,
        member_count=member.guild.member_count,
    )
    embed = discord.Embed(description=text, color=COLOR)
    from utils.emojis import emoji
    embed.set_author(name=f"{emoji(member.guild, 'wave')} ¡Bienvenido al servidor, {member.display_name}!")
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🆔 Usuario", value=member.mention, inline=True)
    embed.add_field(name="👥 Miembros totales", value=f"`{member.guild.member_count}`", inline=True)
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text="SoulBot System", icon_url=get_footer_icon())
    return embed


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = {}

    async def cache_guild_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            return
        self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in invites}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        config = await get_guild_config(guild.id)

        inviter_id = None
        try:
            new_invites = await guild.invites()
            old = self.invite_cache.get(guild.id, {})
            for inv in new_invites:
                if (inv.uses or 0) > old.get(inv.code, 0):
                    inviter_id = inv.inviter.id if inv.inviter else None
                    break
            self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in new_invites}
        except discord.Forbidden:
            pass

        if inviter_id:
            await db().execute(
                """INSERT INTO invites (guild_id, user_id, invited_count) VALUES (?, ?, 1)
                   ON CONFLICT(guild_id, user_id) DO UPDATE SET invited_count = invited_count + 1""",
                (guild.id, inviter_id),
            )
            await db().commit()

        if not config["welcome_enabled"] or not config["welcome_channel_id"]:
            return

        channel = guild.get_channel(config["welcome_channel_id"])
        if channel is None:
            return

        template = config["welcome_message"] or DEFAULT_WELCOME
        embed = build_welcome_embed(member, template)
        try:
            from utils.card_renderer import render_welcome
            buf = await render_welcome(
                member.display_name,
                member.display_avatar.url,
                guild.name,
                guild.icon.url if guild.icon else None,
                guild.member_count,
            )
            file = discord.File(buf, filename="welcome.png")
            embed.set_image(url="attachment://welcome.png")
            await channel.send(content=member.mention, embed=embed, file=file)
        except Exception:
            await channel.send(content=member.mention, embed=embed)

    invites_group = app_commands.Group(name="invites", description="Sistema de invitaciones")

    @invites_group.command(name="count", description="Muestra tus invitaciones o las de otro usuario")
    @app_commands.describe(user="Usuario a consultar (opcional)")
    async def invites_count(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        cur = await db().execute(
            "SELECT invited_count, left_count FROM invites WHERE guild_id = ? AND user_id = ?",
            (interaction.guild_id, target.id),
        )
        row = await cur.fetchone()
        invited, left = row if row else (0, 0)
        current = max(invited - left, 0)

        embed = success_embed(
            f"📨 Invitaciones: **{invited}**\n"
            f"👥 Usuarios actuales: **{current}**\n"
            f"🚪 Usuarios que se fueron: **{left}**",
            title=f"🎟️ Invitaciones de {target.display_name}",
        )
        await interaction.response.send_message(embed=embed)

    @invites_group.command(name="leaderboard", description="Ranking de invitaciones del servidor")
    async def invites_leaderboard(self, interaction: discord.Interaction):
        cur = await db().execute(
            """SELECT user_id, invited_count FROM invites
               WHERE guild_id = ? ORDER BY invited_count DESC LIMIT 10""",
            (interaction.guild_id,),
        )
        rows = await cur.fetchall()

        if not rows:
            await interaction.response.send_message(
                embed=error_embed("Todavía no hay invitaciones registradas.", "🏆 Invite Leaderboard")
            )
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (user_id, count) in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            lines.append(f"{prefix} <@{user_id}> — **{count}**")

        embed = success_embed("\n".join(lines), title="🏆 Invite Leaderboard")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
