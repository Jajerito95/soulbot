from __future__ import annotations
import discord
from discord.ext import commands

from database import get_guild_config, log_staff_action
from config import COLOR, COLOR_ERROR


def log_embed(title: str, description: str, color: int = COLOR) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text="SoulBot System")
    return embed


class LogsCog(commands.Cog):
    """Logs ligeros del servidor. Base pensada para el futuro /sanction."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _channel(self, guild: discord.Guild, category: str) -> discord.TextChannel | None:
        config = await get_guild_config(guild.id)
        if not config["logs_channel_id"] or not config.get(category, 1):
            return None
        return guild.get_channel(config["logs_channel_id"])

    async def _send(self, guild: discord.Guild, category: str, embed: discord.Embed):
        channel = await self._channel(guild, category)
        if channel:
            await channel.send(embed=embed)

    # ---------- miembros ----------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        embed = log_embed("👤 Miembro entró", f"{member.mention} (`{member.id}`)")
        await self._send(member.guild, "logs_members", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Comprueba si fue un kick reciente (audit log) para no duplicar con on_member_ban
        kicked_by = None
        try:
            async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                if entry.target.id == member.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                    kicked_by = entry.user
                    break
        except discord.Forbidden:
            pass

        if kicked_by:
            embed = log_embed(
                "👢 Miembro expulsado",
                f"👤 Usuario: {member.mention} (`{member.id}`)\n🛡️ Staff: {kicked_by.mention}",
                color=COLOR_ERROR,
            )
            await self._send(member.guild, "logs_moderation", embed)
            await log_staff_action(member.guild.id, member.id, kicked_by.id, "kick")
        else:
            embed = log_embed("🚪 Miembro salió", f"{member.mention} (`{member.id}`)")
            await self._send(member.guild, "logs_members", embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        staff = None
        reason = None
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    staff = entry.user
                    reason = entry.reason
                    break
        except discord.Forbidden:
            pass

        embed = log_embed(
            "🔨 Miembro baneado",
            f"👤 Usuario: {user.mention} (`{user.id}`)\n"
            f"🛡️ Staff: {staff.mention if staff else 'Desconocido'}\n"
            f"📝 Razón: {reason or 'Sin razón'}",
            color=COLOR_ERROR,
        )
        await self._send(guild, "logs_moderation", embed)
        if staff:
            await log_staff_action(guild.id, user.id, staff.id, "ban", reason)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        staff = None
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
                if entry.target.id == user.id:
                    staff = entry.user
                    break
        except discord.Forbidden:
            pass

        embed = log_embed(
            "🔓 Miembro desbaneado",
            f"👤 Usuario: {user.mention} (`{user.id}`)\n🛡️ Staff: {staff.mention if staff else 'Desconocido'}",
        )
        await self._send(guild, "logs_moderation", embed)
        if staff:
            await log_staff_action(guild.id, user.id, staff.id, "unban")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild

        # Timeout aplicado/retirado
        if before.timed_out_until != after.timed_out_until:
            staff = None
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
                    if entry.target.id == after.id:
                        staff = entry.user
                        break
            except discord.Forbidden:
                pass

            if after.timed_out_until:
                embed = log_embed(
                    "⚠️ Timeout aplicado",
                    f"👤 Usuario: {after.mention}\n🛡️ Staff: {staff.mention if staff else 'Desconocido'}\n"
                    f"🕐 Hasta: <t:{int(after.timed_out_until.timestamp())}:F>",
                    color=COLOR_ERROR,
                )
                if staff:
                    await log_staff_action(guild.id, after.id, staff.id, "timeout")
            else:
                embed = log_embed("⚠️ Timeout retirado", f"👤 Usuario: {after.mention}")
            await self._send(guild, "logs_moderation", embed)

        # Roles añadidos/retirados
        before_roles, after_roles = set(before.roles), set(after.roles)
        added = after_roles - before_roles
        removed = before_roles - after_roles
        if added or removed:
            parts = []
            if added:
                parts.append("➕ " + ", ".join(r.mention for r in added))
            if removed:
                parts.append("➖ " + ", ".join(r.mention for r in removed))
            embed = log_embed("👥 Roles actualizados", f"👤 {after.mention}\n" + "\n".join(parts))
            await self._send(guild, "logs_roles", embed)

    # ---------- mensajes ----------

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = message.content or "*(sin contenido de texto)*"
        embed = log_embed(
            "💬 Mensaje eliminado",
            f"👤 Autor: {message.author.mention}\n📍 Canal: {message.channel.mention}\n📝 Contenido: {content[:500]}",
            color=COLOR_ERROR,
        )
        await self._send(message.guild, "logs_messages", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        embed = log_embed(
            "✏️ Mensaje editado",
            f"👤 Autor: {before.author.mention}\n📍 Canal: {before.channel.mention}\n"
            f"**Antes:** {before.content[:400] or '*(vacío)*'}\n**Después:** {after.content[:400] or '*(vacío)*'}",
        )
        await self._send(before.guild, "logs_messages", embed)

    # ---------- roles ----------

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        embed = log_embed("🎭 Rol creado", f"{role.mention} (`{role.id}`)")
        await self._send(role.guild, "logs_roles", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        embed = log_embed("🎭 Rol eliminado", f"**{role.name}** (`{role.id}`)", color=COLOR_ERROR)
        await self._send(role.guild, "logs_roles", embed)

    # ---------- canales ----------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        embed = log_embed("📁 Canal creado", f"{channel.mention if hasattr(channel, 'mention') else channel.name}")
        await self._send(channel.guild, "logs_channels", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        embed = log_embed("📁 Canal eliminado", f"**{channel.name}** (`{channel.id}`)", color=COLOR_ERROR)
        await self._send(channel.guild, "logs_channels", embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LogsCog(bot))
