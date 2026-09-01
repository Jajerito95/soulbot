from __future__ import annotations
import asyncio
import os
import discord
from discord.ext import commands
from discord import app_commands

from config import COLOR
from utils.embeds import success_embed, error_embed

# TTS: intenta ElevenLabs si hay key, si no gTTS
# Se lee en cada _speak para coger cambios de env sin reiniciar import
def _eleven_cfg():
    return os.getenv("ELEVENLABS_API_KEY"), os.getenv("ELEVENLABS_VOICE_ID", "PltXjU3hWkDRqpu9TowY")
try:
    from gtts import gTTS
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False

class VCTtsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        # auto-join cuando alguien entra a un VC y el bot no está
        if before.channel is None and after.channel is not None:
            guild = member.guild
            me = guild.me
            # si el bot ya está en algún VC del guild, no hace nada
            if me.voice and me.voice.channel:
                return
            # solo si el canal no es AFK y tiene permisos
            perms = after.channel.permissions_for(me)
            if not perms.connect or not perms.speak:
                return
            try:
                await after.channel.connect(timeout=5.0, self_deaf=False)
            except discord.ClientException as e:
                # PyNaCl missing -> avisa sin crashear
                if "PyNaCl" in str(e):
                    try:
                        # intenta avisar en el canal de sistema si existe
                        if guild.system_channel:
                            await guild.system_channel.send(embed=error_embed("❌ Voice necesita `PyNaCl`. Añade `PyNaCl` a requirements.txt y redeploya."))
                    except: pass
                pass
            except Exception:
                pass
        # auto-leave si se queda solo
        if before.channel is not None and after.channel is None:
            guild = member.guild
            me = guild.me
            if me.voice and me.voice.channel == before.channel:
                if len([m for m in before.channel.members if not m.bot]) == 0:
                    try: await me.voice.channel.guild.voice_client.disconnect()
                    except: pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return
        # solo si el bot está en VC en ese guild y el mensaje es en un canal de texto visible
        guild = message.guild
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            return
        # evita spam: solo lee mensajes de hasta 200 chars y no comandos
        content = message.content.strip()
        if content.startswith("/") or content.startswith("!") or len(content) > 200:
            return
        # cola por guild para no solapar audios
        async with self._lock(guild.id):
            await self._speak(guild, f"{message.author.display_name} dice: {content}")

    async def _speak(self, guild: discord.Guild, text: str):
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            return
        # espera a que termine lo anterior
        while vc.is_playing():
            await asyncio.sleep(0.5)
        # genera audio
        audio_path = None
        try:
            # intenta ElevenLabs si hay key (voice español PltXjU3hWkDRqpu9TowY)
            eleven_key, eleven_voice = _eleven_cfg()
            if eleven_key:
                try:
                    import aiohttp
                    async with aiohttp.ClientSession() as s:
                        async with s.post(
                            f"https://api.elevenlabs.io/v1/text-to-speech/{eleven_voice}/stream",
                            headers={"xi-api-key": eleven_key, "Content-Type": "application/json"},
                            json={"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.6, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}},
                            timeout=aiohttp.ClientTimeout(total=12),
                        ) as r:
                            if r.status == 200:
                                data = await r.read()
                                audio_path = f"/tmp/tts_{guild.id}.mp3"
                                open(audio_path, "wb").write(data)
                            else:
                                # log error sin exponer key
                                try: print(f"[vc_tts] ElevenLabs {r.status}: {await r.text()[:200]}")
                                except: pass
                except Exception as e:
                    try: print(f"[vc_tts] ElevenLabs fail: {e}")
                    except: pass
                    audio_path = None
            if not audio_path and HAS_GTTS:
                audio_path = f"/tmp/tts_{guild.id}.mp3"
                # tld=es para voz española nativa, no china; slow=False reduce delay
                tts = gTTS(text=text, lang="es", tld="es", slow=False)
                await asyncio.to_thread(tts.save, audio_path)
            if not audio_path or not os.path.exists(audio_path):
                return
            # reproduce con ffmpeg — Opus es más estable que PCM y evita entrecortado
            try:
                # verifica ffmpeg existe
                import shutil
                if not shutil.which("ffmpeg"):
                    print("[vc_tts] ffmpeg NO encontrado — instala ffmpeg en buildCommand")
                # intenta Opus (menos delay) y fallback a PCM
                try:
                    source = discord.FFmpegOpusAudio(audio_path, options="-loglevel quiet")
                except Exception as ex:
                    print(f"[vc_tts] Opus fail {ex}, fallback PCM")
                    source = discord.FFmpegPCMAudio(audio_path, options="-loglevel quiet -ar 48000 -ac 2")
                # volumen 100% sin distorsión (Opus no necesita transformer, PCM sí)
                if isinstance(source, discord.FFmpegPCMAudio):
                    source = discord.PCMVolumeTransformer(source, volume=0.9)
                print(f"[vc_tts] playing {audio_path} ({len(open(audio_path,'rb').read())} bytes) in {guild.name}")
                vc.play(source)
                while vc.is_playing():
                    await asyncio.sleep(0.25)
                print("[vc_tts] playback finished")
            except discord.ClientException as ce:
                print(f"[vc_tts] ClientException: {ce}")
            except Exception as e:
                try: print(f"[vc_tts] play fail: {e}")
                except: pass
        finally:
            try:
                if audio_path and os.path.exists(audio_path):
                    os.remove(audio_path)
            except: pass

    # ---------- comandos mixtos (auto + staff) ----------
    vc_group = app_commands.Group(name="vc", description="Dinámicas de VoiceChat", default_permissions=discord.Permissions(manage_guild=True))

    @vc_group.command(name="join", description="Hace que el bot se una a tu VC (o al indicado)")
    async def vc_join(self, interaction: discord.Interaction, canal: discord.VoiceChannel | None = None):
        target = canal or (interaction.user.voice.channel if interaction.user.voice else None)
        if not target:
            await interaction.response.send_message(embed=error_embed("Únete a un VC primero o indica uno."), ephemeral=True)
            return
        perms = target.permissions_for(interaction.guild.me)
        if not perms.connect or not perms.speak:
            await interaction.response.send_message(embed=error_embed("No tengo permisos para conectarme/hablar ahí."), ephemeral=True)
            return
        try:
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(target)
            else:
                await target.connect(self_deaf=False)
            await interaction.response.send_message(embed=success_embed(f"Conectado a {target.mention} 🔊\nAhora leo el chat por TTS (gTTS/ElevenLabs)."), ephemeral=True)
        except discord.ClientException as e:
            if "PyNaCl" in str(e):
                await interaction.response.send_message(embed=error_embed("❌ Voice necesita `PyNaCl` — estoy redeplegando. Espera 2-3 min y prueba `/vc join` de nuevo. Si sigue, haz `Clear build cache & Deploy` en Render."), ephemeral=True)
            else:
                await interaction.response.send_message(embed=error_embed(str(e)), ephemeral=True)
        except Exception as e:
            if "PyNaCl" in str(e):
                await interaction.response.send_message(embed=error_embed("❌ Voice necesita `PyNaCl` — redeploy en curso, espera 2-3 min."), ephemeral=True)
            else:
                await interaction.response.send_message(embed=error_embed(str(e)), ephemeral=True)

    @vc_group.command(name="leave", description="Desconecta al bot del VC")
    async def vc_leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message(embed=error_embed("No estoy en ningún VC."), ephemeral=True)
            return
        await vc.disconnect()
        await interaction.response.send_message(embed=success_embed("Desconectado."), ephemeral=True)

    @vc_group.command(name="debate", description="Inicia un debate/juego en tu VC actual")
    @app_commands.describe(tema="Tema del debate/juego")
    async def vc_debate(self, interaction: discord.Interaction, tema: str):
        vc = interaction.guild.voice_client or (await (interaction.user.voice.channel.connect() if interaction.user.voice and interaction.user.voice.channel else None))
        # si no hay vc, usa el del usuario
        if not interaction.guild.voice_client:
            if not interaction.user.voice or not interaction.user.voice.channel:
                await interaction.response.send_message(embed=error_embed("Únete a un VC primero."), ephemeral=True)
                return
            try: await interaction.user.voice.channel.connect(self_deaf=False)
            except Exception as e:
                await interaction.response.send_message(embed=error_embed(str(e)), ephemeral=True)
                return
        await interaction.response.send_message(embed=success_embed(f"🎙️ Debate iniciado en {interaction.user.voice.channel.mention}\n**Tema:** {tema}\nRecompensa: XP + SoulCoins por participar", title="🎙️ Dinámica VC"), ephemeral=False)
        # XP por participar se da vía levels voice_xp_loop ya existente + bonus manual si se quiere
        # el TTS ya lee el chat automáticamente

    @vc_group.command(name="tts", description="Haz que el bot diga algo por TTS en el VC")
    @app_commands.describe(texto="Texto a decir (máx 200)")
    async def vc_tts(self, interaction: discord.Interaction, texto: str):
        if len(texto) > 200:
            await interaction.response.send_message(embed=error_embed("Máximo 200 caracteres."), ephemeral=True)
            return
        vc = interaction.guild.voice_client
        if not vc or not vc.is_connected():
            await interaction.response.send_message(embed=error_embed("No estoy en ningún VC. Usa /vc join primero."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._speak(interaction.guild, texto)
        await interaction.followup.send(embed=success_embed(f"🔊 TTS: *{texto[:80]}*"), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(VCTtsCog(bot))
