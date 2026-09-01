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
    k = os.getenv("ELEVENLABS_API_KEY")
    v = os.getenv("ELEVENLABS_VOICE_ID", "PltXjU3hWkDRqpu9TowY")
    try:
        print(f"[vc_tts] cfg key={'SET' if k else 'MISSING'} voice={v}", flush=True)
    except: pass
    return k, v
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
        while vc.is_playing():
            await asyncio.sleep(0.4)
        # --- PIPE STREAMING (instant ~0.7s) para ElevenLabs ---
        eleven_key, eleven_voice = _eleven_cfg()
        if eleven_key:
            try:
                import aiohttp, subprocess, shutil
                if not shutil.which("ffmpeg"):
                    print("[vc_tts] ffmpeg missing")
                else:
                    # ffmpeg: mp3 stdin -> s16le stdout para discord PCMAudio
                    proc = subprocess.Popen(
                        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
                    )
                    loop = asyncio.get_running_loop()
                    success = False
                    async def _feed():
                        nonlocal success
                        try:
                            async with aiohttp.ClientSession() as sess:
                                async with sess.post(
                                    f"https://api.elevenlabs.io/v1/text-to-speech/{eleven_voice}/stream?optimize_streaming_latency=4",
                                    headers={"xi-api-key": eleven_key, "Content-Type": "application/json"},
                                    json={"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.6, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}},
                                    timeout=aiohttp.ClientTimeout(total=12),
                                ) as resp:
                                    if resp.status != 200:
                                        try: print(f"[vc_tts] Eleven {resp.status}: {(await resp.text())[:150]}")
                                        except: pass
                                        try: proc.stdin.close()
                                        except: pass
                                        return
                                    async for chunk in resp.content.iter_chunked(2048):
                                        if chunk:
                                            await loop.run_in_executor(None, proc.stdin.write, chunk)
                                    try: proc.stdin.close()
                                    except: pass
                                    success = True
                        except Exception as e:
                            try: print(f"[vc_tts] pipe feed fail: {e}")
                            except: pass
                            try: proc.stdin.close()
                            except: pass
                    feed_task = asyncio.create_task(_feed())
                    # deja que ffmpeg bufferice 200ms antes de play
                    await asyncio.sleep(0.35)
                    # si el proc murió rápido, fallback a file
                    if proc.poll() is not None and not success:
                        print("[vc_tts] pipe ffmpeg died, fallback to file")
                    else:
                        try:
                            source = discord.PCMAudio(proc.stdout)
                            source = discord.PCMVolumeTransformer(source, volume=0.9)
                            print(f"[vc_tts] pipe streaming '{text[:30]}' in {guild.name}")
                            vc.play(source, after=lambda e: print(f"[vc_tts] pipe after: {e}"))
                            while vc.is_playing():
                                await asyncio.sleep(0.2)
                            await feed_task
                            try: proc.terminate()
                            except: pass
                            try: proc.wait(timeout=1)
                            except: pass
                            if success:
                                print("[vc_tts] pipe playback finished")
                                return
                        except Exception as e:
                            try: print(f"[vc_tts] pipe play fail: {e}")
                            except: pass
                            try: proc.terminate()
                            except: pass
            except Exception as e:
                try: print(f"[vc_tts] pipe setup fail: {e}", flush=True)
                except: pass
        # --- EDGE-TTS PIPE (free, español instant) ---
        try:
            import shutil, subprocess
            edge_voice = os.getenv("EDGE_TTS_VOICE", "es-ES-AlvaroNeural")
            if shutil.which("ffmpeg"):
                try:
                    import edge_tts
                    proc2 = subprocess.Popen(
                        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
                    )
                    loop2 = asyncio.get_running_loop()
                    edge_success = False
                    async def _edge_feed():
                        nonlocal edge_success
                        try:
                            comm = edge_tts.Communicate(text, voice=edge_voice)
                            async for chunk in comm.stream():
                                if chunk["type"] == "audio":
                                    data = chunk["data"]
                                    await loop2.run_in_executor(None, proc2.stdin.write, data)
                            try: proc2.stdin.close()
                            except: pass
                            edge_success = True
                        except Exception as ee:
                            try: print(f"[vc_tts] edge feed fail: {ee}", flush=True)
                            except: pass
                            try: proc2.stdin.close()
                            except: pass
                    edge_task = asyncio.create_task(_edge_feed())
                    await asyncio.sleep(0.25)
                    if proc2.poll() is None or edge_success:
                        try:
                            source = discord.PCMAudio(proc2.stdout)
                            source = discord.PCMVolumeTransformer(source, volume=0.9)
                            print(f"[vc_tts] edge pipe streaming '{text[:30]}' voice={edge_voice} in {guild.name}", flush=True)
                            vc.play(source, after=lambda e: print(f"[vc_tts] edge after: {e}", flush=True))
                            while vc.is_playing():
                                await asyncio.sleep(0.2)
                            await edge_task
                            try: proc2.terminate()
                            except: pass
                            try: proc2.wait(timeout=1)
                            except: pass
                            if edge_success:
                                print("[vc_tts] edge pipe finished", flush=True)
                                return
                        except Exception as ee:
                            try: print(f"[vc_tts] edge play fail: {ee}", flush=True)
                            except: pass
                            try: proc2.terminate()
                            except: pass
                except ImportError:
                    print("[vc_tts] edge-tts not installed", flush=True)
                except Exception as ee:
                    try: print(f"[vc_tts] edge setup fail: {ee}", flush=True)
                    except: pass
        except Exception:
            pass
        # --- FALLBACK FILE (gTTS o ElevenLabs sin pipe) ---
        audio_path = None
        try:
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
                                try: print(f"[vc_tts] ElevenLabs file {r.status}: {(await r.text())[:150]}")
                                except: pass
                except Exception as e:
                    try: print(f"[vc_tts] ElevenLabs file fail: {e}")
                    except: pass
                    audio_path = None
            if not audio_path and HAS_GTTS:
                audio_path = f"/tmp/tts_{guild.id}.mp3"
                tts = gTTS(text=text, lang="es", tld="es", slow=False)
                await asyncio.to_thread(tts.save, audio_path)
            if not audio_path or not os.path.exists(audio_path):
                return
            try:
                import shutil
                if not shutil.which("ffmpeg"):
                    print("[vc_tts] ffmpeg missing (file mode)")
                try:
                    source = discord.FFmpegOpusAudio(audio_path, options="-loglevel quiet")
                except Exception as ex:
                    print(f"[vc_tts] Opus fail {ex}, fallback PCM")
                    source = discord.FFmpegPCMAudio(audio_path, options="-loglevel quiet -ar 48000 -ac 2")
                if isinstance(source, discord.FFmpegPCMAudio):
                    source = discord.PCMVolumeTransformer(source, volume=0.9)
                print(f"[vc_tts] file playing {audio_path} ({len(open(audio_path,'rb').read())} bytes)")
                vc.play(source)
                while vc.is_playing():
                    await asyncio.sleep(0.25)
                print("[vc_tts] file playback finished")
            except discord.ClientException as ce:
                print(f"[vc_tts] ClientException file: {ce}")
            except Exception as e:
                try: print(f"[vc_tts] play file fail: {e}")
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
