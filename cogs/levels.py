from __future__ import annotations
import random
import time
import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from utils.embeds import success_embed, error_embed, base_embed, get_footer_icon
from utils.levels_engine import award_xp, level_from_xp, progress_bar, xp_for_level
from config import COLOR, COLOR_ERROR, RESET_PASSWORD

MESSAGE_COOLDOWN = 60  # segundos
MESSAGE_XP_RANGE = (15, 25)
VOICE_XP_PER_MINUTE = 10


def parse_duration(text: str) -> Optional[str]:
    """Convierte '2h', '3d', '30m' en un timestamp ISO futuro. None = permanente."""
    if not text or text.lower() in ("perm", "permanente", "0"):
        return None
    unit = text[-1].lower()
    try:
        amount = int(text[:-1])
    except ValueError:
        return None
    delta_map = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    if unit not in delta_map:
        return None
    delta = datetime.timedelta(**{delta_map[unit]: amount})
    return (datetime.datetime.utcnow() + delta).isoformat()


class LevelsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_message: dict[int, float] = {}
        self.voice_xp_loop.start()
        self.import_jobs: dict[int, bool] = {}  # guild_id -> cancel_flag

    def cog_unload(self):
        self.voice_xp_loop.cancel()

    # ---------- ganancia de XP ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        config = await db.get_guild_config(message.guild.id)
        if not config["levels_enabled"]:
            return
        now = time.time()
        last = self.last_message.get(message.author.id, 0)
        if now - last < MESSAGE_COOLDOWN:
            return
        self.last_message[message.author.id] = now

        amount = random.randint(*MESSAGE_XP_RANGE)
        result = await award_xp(message.guild, message.author, amount)
        if result["leveled_up"]:
            await self._announce_levelup(message.guild, message.author, result, message.channel)

    @tasks.loop(minutes=1)
    async def voice_xp_loop(self):
        for guild in self.bot.guilds:
            config = await db.get_guild_config(guild.id)
            if not config["levels_enabled"]:
                continue
            for channel in guild.voice_channels:
                if channel == guild.afk_channel:
                    continue
                for member in channel.members:
                    if member.bot:
                        continue
                    if member.voice and (member.voice.self_deaf or member.voice.deaf):
                        continue
                    result = await award_xp(guild, member, VOICE_XP_PER_MINUTE)
                    if result["leveled_up"]:
                        await self._announce_levelup(guild, member, result, None)

    @voice_xp_loop.before_loop
    async def before_voice_loop(self):
        await self.bot.wait_until_ready()

    async def _announce_levelup(self, guild: discord.Guild, member: discord.Member, result: dict, fallback_channel):
        config = await db.get_guild_config(guild.id)
        channel = None
        if config.get("levels_announce_channel_id"):
            channel = guild.get_channel(config["levels_announce_channel_id"])
        channel = channel or fallback_channel
        if not channel:
            return

        desc = f"🎉 {member.mention} ha subido a **nivel {result['new_level']}**!"
        if result.get("coins_awarded"):
            desc += f"\n💰 +{result['coins_awarded']} SoulCoins"
        if result["new_roles"]:
            desc += "\n🎁 Nuevo rol: " + ", ".join(r.mention for r in result["new_roles"])
        try:
            await channel.send(embed=success_embed(desc, title="⭐ ¡Level Up!"))
        except discord.Forbidden:
            pass

    # ---------- comandos de miembro ----------

    @app_commands.command(name="level", description="Muestra tu nivel o el de otro usuario")
    @app_commands.describe(usuario="Usuario a consultar (opcional)")
    async def level(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        target = usuario or interaction.user
        data = await db.get_level_data(interaction.guild_id, target.id)
        level, xp_in_level, xp_needed = level_from_xp(data["xp"])
        bar = progress_bar(xp_in_level, xp_needed)

        embed = base_embed(
            f"⭐ Nivel: **{level}**\n✨ XP total: **{data['xp']}**\n{bar} `{xp_in_level}/{xp_needed}`",
            COLOR,
            title=f"📊 {target.display_name}",
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="card", description="Ve y personaliza tu tarjeta de nivel")
    @app_commands.describe(usuario="Usuario a consultar (opcional)", color="Color HEX para personalizar tu tarjeta (ej: #5865F2)")
    async def card(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None, color: Optional[str] = None):
        target = usuario or interaction.user

        if color:
            if usuario and usuario.id != interaction.user.id:
                await interaction.response.send_message(embed=error_embed("Solo puedes cambiar el color de tu propia tarjeta."), ephemeral=True)
                return
            from utils.embeds import is_valid_hex
            if not is_valid_hex(color):
                await interaction.response.send_message(embed=error_embed("Color HEX inválido. Ejemplo: `#5865F2`"), ephemeral=True)
                return
            await db.set_card_color(interaction.guild_id, interaction.user.id, color)

        saved_color = await db.get_card_color(interaction.guild_id, target.id)
        from utils.embeds import hex_to_int
        embed_color = hex_to_int(saved_color) if saved_color else COLOR

        data = await db.get_level_data(interaction.guild_id, target.id)
        level, xp_in_level, xp_needed = level_from_xp(data["xp"])
        bar = progress_bar(xp_in_level, xp_needed)

        top = await db.get_leaderboard_alltime(interaction.guild_id, limit=1000)
        position = next((i + 1 for i, row in enumerate(top) if row[0] == target.id), len(top) + 1 if top else 1)

        embed = discord.Embed(color=embed_color)
        embed.set_author(name=f"🎴 Tarjeta de {target.display_name}")
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="⭐ Nivel", value=f"`{level}`", inline=True)
        embed.add_field(name="🏆 Posición", value=f"`#{position}`", inline=True)
        embed.add_field(name="✨ XP total", value=f"`{data['xp']}`", inline=True)
        embed.add_field(name="📈 Progreso", value=f"{bar} `{xp_in_level}/{xp_needed}`", inline=False)
        embed.set_footer(text="SoulBot System", icon_url=get_footer_icon())
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Top 10 del servidor por XP")
    @app_commands.describe(periodo="Periodo del ranking")
    @app_commands.choices(periodo=[
        app_commands.Choice(name="All Time", value="alltime"),
        app_commands.Choice(name="Mensual", value="monthly"),
        app_commands.Choice(name="Diario", value="daily"),
    ])
    async def leaderboard(self, interaction: discord.Interaction, periodo: Optional[app_commands.Choice[str]] = None):
        await self._send_leaderboard(interaction, periodo.value if periodo else "alltime")

    @app_commands.command(name="lb", description="Alias de /leaderboard")
    @app_commands.describe(periodo="Periodo del ranking")
    @app_commands.choices(periodo=[
        app_commands.Choice(name="All Time", value="alltime"),
        app_commands.Choice(name="Mensual", value="monthly"),
        app_commands.Choice(name="Diario", value="daily"),
    ])
    async def lb(self, interaction: discord.Interaction, periodo: Optional[app_commands.Choice[str]] = None):
        await self._send_leaderboard(interaction, periodo.value if periodo else "alltime")

    async def _send_leaderboard(self, interaction: discord.Interaction, periodo: str):
        medals = ["🥇", "🥈", "🥉"]
        if periodo == "alltime":
            rows = await db.get_leaderboard_alltime(interaction.guild_id)
            lines = [f"{medals[i] if i < 3 else f'`#{i+1}`'} <@{r[0]}> — Nivel **{r[2]}** (`{r[1]}` XP)" for i, r in enumerate(rows)]
            title = "🏆 Leaderboard — All Time"
        else:
            days = 30 if periodo == "monthly" else 1
            rows = await db.get_leaderboard_period(interaction.guild_id, days)
            lines = [f"{medals[i] if i < 3 else f'`#{i+1}`'} <@{r[0]}> — `{r[1]}` XP" for i, r in enumerate(rows)]
            title = f"🏆 Leaderboard — {'Mensual' if periodo == 'monthly' else 'Diario'}"

        if not lines:
            lines = ["Todavía no hay datos suficientes."]

        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title=title))

    @app_commands.command(name="rewards", description="Muestra las recompensas de rol por nivel")
    async def rewards(self, interaction: discord.Interaction):
        rewards = await db.get_level_rewards(interaction.guild_id)
        if not rewards:
            await interaction.response.send_message(embed=error_embed("Este servidor no tiene recompensas de nivel configuradas."))
            return
        lines = [f"⭐ Nivel **{level}** → <@&{role_id}>" for level, role_id in rewards]
        await interaction.response.send_message(embed=base_embed("\n".join(lines), COLOR, title="🎁 Recompensas de nivel"))

    # ---------- grupo staff /levels ----------

    levels_group = app_commands.Group(
        name="levels",
        description="Administración del sistema de niveles (Staff)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @levels_group.command(name="enable", description="Reactiva la ganancia de XP en el servidor")
    async def levels_enable(self, interaction: discord.Interaction):
        await db.update_guild_config(interaction.guild_id, levels_enabled=1)
        await interaction.response.send_message(embed=success_embed("✅ Sistema de niveles **activado**. Se vuelve a ganar XP normalmente."))

    @levels_group.command(name="disable", description="Pausa la ganancia de XP (mensajes y voz) sin borrar niveles ya obtenidos")
    async def levels_disable(self, interaction: discord.Interaction):
        await db.update_guild_config(interaction.guild_id, levels_enabled=0)
        await interaction.response.send_message(embed=success_embed("⏸️ Sistema de niveles **pausado**. Nadie ganará XP hasta que uses `/levels enable`. Los niveles y XP actuales no se tocan."))

    @levels_group.command(name="rewardsetup", description="Configura una recompensa de rol para un nivel")
    @app_commands.describe(nivel="Nivel requerido", rol="Rol que se otorga")
    async def rewardsetup(self, interaction: discord.Interaction, nivel: int, rol: discord.Role):
        await db.add_level_reward(interaction.guild_id, nivel, rol.id)
        await interaction.response.send_message(embed=success_embed(f"Nivel **{nivel}** → {rol.mention} configurado."))

    @levels_group.command(name="stats", description="Estadísticas de XP de un usuario en los últimos 7 días")
    @app_commands.describe(usuario="Usuario a consultar")
    async def stats(self, interaction: discord.Interaction, usuario: discord.Member):
        xp_7d = await db.get_xp_gained_since(interaction.guild_id, usuario.id, 7)
        data = await db.get_level_data(interaction.guild_id, usuario.id)
        level, _, _ = level_from_xp(data["xp"])
        embed = base_embed(
            f"⭐ Nivel actual: **{level}**\n✨ XP total: **{data['xp']}**\n📈 XP ganada (7 días): **{xp_7d}**",
            COLOR,
            title=f"📊 Stats de {usuario.display_name}",
        )
        await interaction.response.send_message(embed=embed)

    @levels_group.command(name="xpadd", description="Añade XP manualmente a un usuario")
    @app_commands.describe(usuario="Usuario", cantidad="Cantidad de XP a añadir")
    async def xpadd(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        data = await db.get_level_data(interaction.guild_id, usuario.id)
        new_xp = max(0, data["xp"] + cantidad)
        new_level, _, _ = level_from_xp(new_xp)
        await db.set_level_data(interaction.guild_id, usuario.id, new_xp, new_level)
        await db.log_xp_event(interaction.guild_id, usuario.id, cantidad)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} ahora tiene **{new_xp}** XP (nivel {new_level})."))

    @levels_group.command(name="xpremove", description="Quita XP manualmente a un usuario")
    @app_commands.describe(usuario="Usuario", cantidad="Cantidad de XP a quitar")
    async def xpremove(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        data = await db.get_level_data(interaction.guild_id, usuario.id)
        new_xp = max(0, data["xp"] - cantidad)
        new_level, _, _ = level_from_xp(new_xp)
        await db.set_level_data(interaction.guild_id, usuario.id, new_xp, new_level)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} ahora tiene **{new_xp}** XP (nivel {new_level})."))

    @levels_group.command(name="xpset", description="Fija la XP exacta de un usuario")
    @app_commands.describe(usuario="Usuario", cantidad="XP exacta")
    async def xpset(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        new_level, _, _ = level_from_xp(max(0, cantidad))
        await db.set_level_data(interaction.guild_id, usuario.id, max(0, cantidad), new_level)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} ahora tiene **{cantidad}** XP (nivel {new_level})."))

    @levels_group.command(name="leveladd", description="Añade niveles a un usuario")
    @app_commands.describe(usuario="Usuario", cantidad="Niveles a añadir")
    async def leveladd(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        data = await db.get_level_data(interaction.guild_id, usuario.id)
        level, _, _ = level_from_xp(data["xp"])
        new_level = max(0, level + cantidad)
        new_xp = sum(xp_for_level(l) for l in range(new_level))
        await db.set_level_data(interaction.guild_id, usuario.id, new_xp, new_level)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} ahora es nivel **{new_level}**."))

    @levels_group.command(name="levelremove", description="Quita niveles a un usuario")
    @app_commands.describe(usuario="Usuario", cantidad="Niveles a quitar")
    async def levelremove(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        data = await db.get_level_data(interaction.guild_id, usuario.id)
        level, _, _ = level_from_xp(data["xp"])
        new_level = max(0, level - cantidad)
        new_xp = sum(xp_for_level(l) for l in range(new_level))
        await db.set_level_data(interaction.guild_id, usuario.id, new_xp, new_level)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} ahora es nivel **{new_level}**."))

    @levels_group.command(name="levelset", description="Fija el nivel exacto de un usuario")
    @app_commands.describe(usuario="Usuario", nivel="Nivel exacto")
    async def levelset(self, interaction: discord.Interaction, usuario: discord.Member, nivel: int):
        new_level = max(0, nivel)
        new_xp = sum(xp_for_level(l) for l in range(new_level))
        await db.set_level_data(interaction.guild_id, usuario.id, new_xp, new_level)
        await interaction.response.send_message(embed=success_embed(f"{usuario.mention} ahora es nivel **{new_level}**."))

    @levels_group.command(name="resetmember", description="Resetea el nivel y XP de un usuario")
    @app_commands.describe(usuario="Usuario a resetear")
    async def resetmember(self, interaction: discord.Interaction, usuario: discord.Member):
        await db.reset_member_levels(interaction.guild_id, usuario.id)
        await interaction.response.send_message(embed=success_embed(f"Nivel y XP de {usuario.mention} reseteados."))

    @levels_group.command(name="resetserver", description="⚠️ Resetea TODOS los niveles del servidor (requiere contraseña)")
    @app_commands.describe(contraseña="Contraseña de confirmación")
    async def resetserver(self, interaction: discord.Interaction, contraseña: str):
        if contraseña != RESET_PASSWORD:
            await interaction.response.send_message(embed=error_embed("Contraseña incorrecta. Reset cancelado."), ephemeral=True)
            return
        await db.reset_server_levels(interaction.guild_id)
        await interaction.response.send_message(embed=success_embed("⚠️ Todos los niveles del servidor han sido reseteados."))

    @levels_group.command(name="multiplier", description="Aplica un multiplicador de XP a un usuario (máx x2)")
    @app_commands.describe(usuario="Usuario", multiplicador="Máximo x2", tiempo="Duración: 30m, 2h, 3d... (vacío = permanente)")
    async def multiplier(self, interaction: discord.Interaction, usuario: discord.Member, multiplicador: app_commands.Range[float, 1.0, 2.0], tiempo: str = ""):
        expires = parse_duration(tiempo) if tiempo else None
        await db.set_user_multiplier(interaction.guild_id, usuario.id, multiplicador, expires)
        await interaction.response.send_message(
            embed=success_embed(f"Multiplicador de {usuario.mention}: **x{multiplicador}**" + (f" hasta {tiempo}" if tiempo else " (permanente)"))
        )

    @levels_group.command(name="multiplierglobal", description="Aplica un multiplicador de XP global (máx x5)")
    @app_commands.describe(multiplicador="Máximo x5", tiempo="Duración: 30m, 2h, 3d... (vacío = permanente)")
    async def multiplierglobal(self, interaction: discord.Interaction, multiplicador: app_commands.Range[float, 1.0, 5.0], tiempo: str = ""):
        expires = parse_duration(tiempo) if tiempo else None
        await db.update_guild_config(interaction.guild_id, xp_global_multiplier=multiplicador, xp_global_multiplier_expires=expires)
        await interaction.response.send_message(
            embed=success_embed(f"Multiplicador global: **x{multiplicador}**" + (f" hasta {tiempo}" if tiempo else " (permanente)"))
        )

    @levels_group.command(name="multiplierfds", description="Activa/desactiva el multiplicador de fin de semana (x2, jueves 23h - domingo 23h)")
    @app_commands.describe(activo="true para activar, false para desactivar")
    async def multiplierfds(self, interaction: discord.Interaction, activo: bool):
        await db.update_guild_config(interaction.guild_id, xp_weekend_enabled=int(activo))
        estado = "✅ activado" if activo else "❌ desactivado"
        await interaction.response.send_message(embed=success_embed(f"Multiplicador de fin de semana (x2): {estado}"))

    # ---------- import ----------

    import_group = app_commands.Group(
        name="import",
        description="Importa niveles desde un archivo externo (Staff)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @import_group.command(name="start", description="Inicia una importación de niveles desde un CSV (user_id,level,xp)")
    @app_commands.describe(archivo="Archivo CSV con columnas: user_id,level,xp")
    async def import_start(self, interaction: discord.Interaction, archivo: discord.Attachment):
        existing = await db.get_import_job(interaction.guild_id)
        if existing and existing["status"] == "running":
            await interaction.response.send_message(embed=error_embed("Ya hay una importación en curso. Usa `/import progress` o `/import cancel`."), ephemeral=True)
            return

        await interaction.response.defer()
        raw = (await archivo.read()).decode("utf-8", errors="ignore")
        rows = [line.strip().split(",") for line in raw.splitlines() if line.strip()]
        header = rows[0][0].lower() if rows else ""
        by_username = header in ("username", "user", "usuario", "nombre")
        if rows and rows[0][0].lower() in ("user_id", "usuario", "id", "username", "user", "nombre"):
            rows = rows[1:]

        await db.create_import_job(interaction.guild_id, interaction.user.id, len(rows))
        self.import_jobs[interaction.guild_id] = False

        mode_txt = "por username (buscando en los miembros del servidor)" if by_username else "por user_id"
        await interaction.followup.send(embed=success_embed(f"Importando **{len(rows)}** registros {mode_txt}. Usa `/import progress` para ver el avance."))

        imported = 0
        not_found = []
        for row in rows:
            if self.import_jobs.get(interaction.guild_id):
                await db.set_import_status(interaction.guild_id, "cancelled")
                return
            if len(row) < 3:
                continue
            try:
                level, xp = int(row[1]), int(row[2])
            except ValueError:
                continue

            if by_username:
                username = row[0].strip().lstrip("@").lower()
                member = discord.utils.find(
                    lambda m: m.name.lower() == username or (m.global_name or "").lower() == username,
                    interaction.guild.members,
                )
                if not member:
                    not_found.append(row[0])
                    continue
                user_id = member.id
            else:
                try:
                    user_id = int(row[0])
                except ValueError:
                    continue

            await db.set_level_data(interaction.guild_id, user_id, xp, level)
            imported += 1
            if imported % 25 == 0:
                await db.update_import_progress(interaction.guild_id, imported)

        await db.update_import_progress(interaction.guild_id, imported)
        await db.set_import_status(interaction.guild_id, "done")

        summary = f"✅ Importados: **{imported}**"
        if not_found:
            summary += f"\n⚠️ No encontrados en el servidor ({len(not_found)}): {', '.join(not_found[:15])}" + ("..." if len(not_found) > 15 else "")
        await interaction.channel.send(embed=success_embed(summary, title="📥 Importación completada"))

    @import_group.command(name="progress", description="Muestra el progreso de la importación en curso")
    async def import_progress(self, interaction: discord.Interaction):
        job = await db.get_import_job(interaction.guild_id)
        if not job or job["status"] == "idle":
            await interaction.response.send_message(embed=error_embed("No hay ninguna importación registrada."), ephemeral=True)
            return
        bar = progress_bar(job["progress"], job["total"] or 1)
        await interaction.response.send_message(
            embed=base_embed(f"{bar}\n`{job['progress']}/{job['total']}` • Estado: **{job['status']}**", COLOR, title="📥 Progreso de importación")
        )

    @import_group.command(name="cancel", description="Cancela la importación en curso")
    async def import_cancel(self, interaction: discord.Interaction):
        job = await db.get_import_job(interaction.guild_id)
        if not job or job["status"] != "running":
            await interaction.response.send_message(embed=error_embed("No hay ninguna importación en curso."), ephemeral=True)
            return
        self.import_jobs[interaction.guild_id] = True
        await interaction.response.send_message(embed=success_embed("Importación cancelada. Se detendrá en el siguiente registro."))


async def setup(bot: commands.Bot):
    await bot.add_cog(LevelsCog(bot))
