"""
cog.py — Módulo de música para Discord (Cog).

Contiene todos los comandos (!play, /play, etc.), los eventos de Discord,
el manejo de notas de voz, y voice receive.

Si este módulo falla al cargar, el bot sigue arrancando sin música.
"""

import os
import asyncio
import subprocess
import tempfile

import discord
from discord.ext import commands
from dotenv import load_dotenv

from command_parser import full_parse
import responses as R

from .player   import get_player, MusicPlayer
from .sink     import LiveTranscriptionSink, transcribe_pcm, HAS_NUMPY, HAS_SR

load_dotenv()

OWNER_USER_ID            = int(os.getenv("DISCORD_OWNER_USER_ID",  "0") or 0)
DEFAULT_VOICE_CHANNEL_ID = int(os.getenv("DISCORD_VOICE_CHANNEL_ID", "0") or 0)
GUILD_ID                 = int(os.getenv("DISCORD_GUILD_ID",         "0") or 0)
WHISPER_MODEL            = os.getenv("WHISPER_MODEL", "small")
VOICE_MSG_ENABLED        = os.getenv("VOICE_MSG_ENABLED",    "true").lower()  == "true"
VOICE_LISTEN_ENABLED     = os.getenv("VOICE_LISTEN_ENABLED", "false").lower() == "true"

_slash_guild_kwargs = {"guild_ids": [GUILD_ID]} if GUILD_ID else {}


# ─── Helpers de guild / canal ─────────────────────────────────────────────────

def get_target_guild(bot):
    if GUILD_ID:
        return bot.get_guild(GUILD_ID)
    return bot.guilds[0] if bot.guilds else None


async def find_voice_channel(guild):
    """1) Canal del dueño  2) Canal por defecto  3) Primer canal con humanos."""
    if not guild:
        return None
    if OWNER_USER_ID:
        vs = guild._voice_states.get(OWNER_USER_ID)
        if vs and vs.channel:
            return vs.channel
        member = guild.get_member(OWNER_USER_ID)
        if member and member.voice and member.voice.channel:
            return member.voice.channel
        try:
            member = await guild.fetch_member(OWNER_USER_ID)
            if member and member.voice and member.voice.channel:
                return member.voice.channel
        except Exception:
            pass
    if DEFAULT_VOICE_CHANNEL_ID:
        c = guild.get_channel(DEFAULT_VOICE_CHANNEL_ID)
        if c:
            return c
    for vc in guild.voice_channels:
        if any(not m.bot for m in vc.members):
            return vc
    return None


def find_member_by_name(guild, name: str):
    """
    Busca un miembro por nombre (display_name o username).
    Prioridad: exacto en canal de voz → exacto en servidor → parcial en canal → parcial en servidor.
    "Brayan" matchea "Brayan_04", "Brayan López", etc.
    """
    if not guild or not name:
        return None
    clean = name.replace("🎤", "").strip().lower()

    # Miembros actualmente en canales de voz (más probable que sea el target)
    voice_members = [m for vc in guild.voice_channels for m in vc.members if not m.bot]

    # 1. Exacto en canal de voz
    for m in voice_members:
        if m.name.lower() == clean or m.display_name.lower() == clean:
            return m

    # 2. Exacto en todo el servidor
    for m in guild.members:
        if m.name.lower() == clean or m.display_name.lower() == clean:
            return m

    # 3. Parcial en canal de voz (ej: "Brayan" matchea "Brayan_04")
    for m in voice_members:
        dn = m.display_name.lower()
        un = m.name.lower()
        if clean in dn or dn.startswith(clean) or clean in un or un.startswith(clean):
            return m

    # 4. Parcial en todo el servidor
    for m in guild.members:
        dn = m.display_name.lower()
        un = m.name.lower()
        if clean in dn or dn.startswith(clean) or clean in un or un.startswith(clean):
            return m

    return None


# ─── Cog principal ────────────────────────────────────────────────────────────

class MusicCog(commands.Cog, name="Música"):
    """Módulo de reproducción de música para Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Evento: bot listo ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"[MÚSICA] Módulo listo.")
        if VOICE_MSG_ENABLED:
            print(f"[VOICE-MSG] ✅ Notas de voz activadas (Whisper {WHISPER_MODEL}).")

    # ── Voice receive: conectar el sink cuando el bot entra al canal ───────────

    async def _attach_voice_sink(self, player: MusicPlayer):
        """Inicia voice receive en el voice_client del player si está habilitado."""
        if not (VOICE_LISTEN_ENABLED and HAS_NUMPY and HAS_SR):
            return
        vc = player.voice_client
        if not vc or getattr(vc, "_listen_started", False):
            return
        try:
            sink = LiveTranscriptionSink(
                on_speech = self._on_user_voice_speech,
                owner_id  = OWNER_USER_ID,
                bot_id    = self.bot.user.id if self.bot.user else 0,
                bot_loop  = self.bot.loop,
            )
            vc.start_recording(sink, lambda *a: None)
            vc._listen_started = True
            print("[VOICE-IN] Escuchando comandos del canal de voz.")
        except Exception as e:
            print(f"[VOICE-IN] ⚠️  No se pudo iniciar voice receive: {e}")
            print("[VOICE-IN]    Discord DAVE rompe la recepción en py-cord (issue #3139).")

    # ── Evento: cambios de estado de voz (auto-disconnect) ────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id == self.bot.user.id:
            return
        from .player import _players
        player = _players.get(member.guild.id)
        if not player or not player.voice_client:
            return
        bot_vc = player.voice_client.channel
        if bot_vc:
            non_bots = [m for m in bot_vc.members if not m.bot]
            if len(non_bots) == 0:
                print(f"[BOT] Canal vacío — desconectando de {bot_vc.name}.")
                try:
                    await player.disconnect()
                except Exception as e:
                    print(f"[BOT] Error al desconectar: {e}")

    # ── Voice receive: callback cuando alguien termina de hablar ──────────────

    async def _on_user_voice_speech(self, pcm_bytes: bytes, user_id: int):
        text = await transcribe_pcm(pcm_bytes)
        if not text:
            return
        guild = get_target_guild(self.bot)
        member_name = ""
        if guild:
            m = guild.get_member(user_id)
            if m:
                member_name = m.display_name
        print(f"[VOICE-IN] {member_name or user_id}: {text}")
        parsed = full_parse(text, require_activator=True)
        if parsed["action"] in ("ignored", "unknown", "greet"):
            return
        print(f"[VOICE-IN] → {parsed}")
        await self._execute_action(parsed, member_name)

    # ── Acción unificada (voice receive + voice msgs + companion) ─────────────

    async def _execute_action(self, parsed: dict, who: str = "", message=None):
        """Ejecuta cualquier acción de música. message es opcional para reply."""
        action = parsed["action"]
        guild  = get_target_guild(self.bot)
        if not guild:
            return
        player  = get_player(guild.id)
        channel = await find_voice_channel(guild)
        if channel:
            await player.connect(channel)
            await self._attach_voice_sink(player)

        async def _reply(text: str, emoji: str = ""):
            if message:
                await message.reply(f"{emoji} {text}".strip())

        if action == "play_music":
            query = parsed.get("query")
            if not query:
                await _reply("¿Qué quieres que ponga? Intenta: *Rodolfo pon despacito*")
                await player.say(R.error_no_query())
                return
            try:
                tracks, started_now = await player.add(
                    query,
                    shuffle=parsed.get("shuffle", False),
                    spotify_type=parsed.get("spotify_type"),
                )
                if tracks:
                    title  = tracks[0]["title"][:60]
                    prefix = "🎵 Sonando" if started_now else "📋 En cola"
                    await _reply(f"**{title}**", prefix)
                    await player.say(
                        R.music_started(title) if started_now else R.music_queued(title)
                    )
            except Exception as e:
                await _reply(f"Error: {e}", "❌")
                await player.say(R.error_not_found())

        elif action == "queue_music":
            query = parsed.get("query")
            if not query:
                return
            try:
                tracks, _ = await player.add(
                    query,
                    shuffle=parsed.get("shuffle", False),
                    spotify_type=parsed.get("spotify_type"),
                )
                if tracks:
                    title = tracks[0]["title"][:60]
                    await _reply(f"**{title}**", "📋 En cola:")
                    await player.say(R.music_queued(title))
            except Exception as e:
                await _reply(f"Error: {e}", "❌")
                await player.say(R.error_generic())

        elif action == "skip_music":
            player.skip()
            await _reply("Siguiente.", "⏭️")
            await player.say(R.music_skipped())

        elif action == "stop_music":
            player.stop()
            await _reply("Música detenida.", "⏹️")
            await player.say(R.music_stopped())

        elif action == "pause_music":
            if player.pause():
                await _reply("Pausa.", "⏸️")
                await player.say(R.music_paused())
            else:
                await _reply("No hay nada sonando.", "")

        elif action == "resume_music":
            if player.resume():
                await _reply("Reanudando.", "▶️")
                await player.say(R.music_resumed())
            else:
                await _reply("No hay nada pausado.", "")

        elif action == "clear_queue":
            n = player.clear_queue()
            await _reply(
                f"Quité {n} canciones de la cola." if n > 0 else "La cola estaba vacía.",
                "🗑️"
            )
            await player.say(R.queue_cleared(n))

        elif action == "remove_last":
            removed = player.remove_last()
            if removed:
                await _reply(f"**{removed}**", "🗑️ Eliminada:")
                await player.say(R.queue_last_removed(removed))
            else:
                await _reply("La cola está vacía.")
                await player.say(R.queue_empty_remove())

        elif action == "music_status":
            if player.current:
                title = player.current["title"][:60]
                await _reply(f"**{title}**", "🎵 Sonando:")
                await player.say(R.music_status(title))
            else:
                await _reply("No hay música sonando.")
                await player.say(R.music_status_nothing())

        elif action == "disconnect_music":
            await player.say(R.disconnected())
            await player.disconnect()
            await _reply("Bye.", "👋")

        elif action == "help":
            help_text = (
                "Para música di: Rodolfo pon y la canción. "
                "También: Rodolfo siguiente, Rodolfo pausa, Rodolfo sigue, "
                "Rodolfo limpia la cola, Rodolfo detén la música."
            )
            if message:
                await message.reply(
                    "📖 **Comandos de música:**\n"
                    "- `Rodolfo pon [canción o URL]`\n"
                    "- `Rodolfo luego pon [canción]` / `encola [canción]`\n"
                    "- `Rodolfo siguiente` / `skip`\n"
                    "- `Rodolfo pausa` / `sigue`\n"
                    "- `Rodolfo limpia la cola`\n"
                    "- `Rodolfo detén la música` / `stop`\n"
                    "- `Rodolfo sal del canal`\n"
                    "- `Rodolfo qué está sonando`"
                )
            await player.say(help_text)

    # ── Evento: mensajes (companion + voice msgs) ──────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        # Notas de voz (archivos de audio en el chat)
        if VOICE_MSG_ENABLED and message.attachments:
            for att in message.attachments:
                is_voice = (
                    (att.content_type and "audio" in att.content_type)
                    or att.filename.endswith((".ogg", ".wav", ".mp3", ".m4a", ".webm"))
                )
                if is_voice and att.size < 1_000_000:
                    await self._handle_voice_message(message, att)

        # Mensajes de texto con activador (companion app / escritos en Discord)
        if VOICE_MSG_ENABLED and message.content and not message.content.startswith("!"):
            text = message.content.strip()
            if text:
                text_lower = text.lower()
                has_act = any(n in text_lower for n in ("rodo", "rodolfo"))
                if has_act:
                    parsed = full_parse(text, require_activator=True)
                    if parsed["action"] not in ("ignored", "unknown", "greet"):
                        print(f"[COMPANION] {message.author.display_name}: '{text}' → {parsed['action']}")
                        await message.add_reaction("🎵")
                        # Buscar canal de voz del autor
                        guild = message.guild
                        if guild:
                            player = get_player(guild.id)
                            channel = None
                            author_member = (
                                find_member_by_name(guild, message.author.name)
                                if message.webhook_id else message.author
                            )
                            if author_member:
                                vs = guild._voice_states.get(author_member.id)
                                if vs and vs.channel:
                                    channel = vs.channel
                            if not channel:
                                channel = await find_voice_channel(guild)
                            if channel:
                                await player.connect(channel)
                            await self._execute_action(parsed, message.author.display_name, message)

    # ── Manejo de notas de voz ─────────────────────────────────────────────────

    async def _handle_voice_message(self, message, attachment):
        tmp = tempfile.NamedTemporaryFile(
            suffix=os.path.splitext(attachment.filename)[1] or ".ogg",
            delete=False,
        )
        tmp_path = tmp.name
        tmp.close()
        try:
            await attachment.save(tmp_path)
            print(f"[VOICE-MSG] Audio de {message.author.display_name} ({attachment.size}B)")
            text = await self._transcribe_voice_message(tmp_path)
            if not text:
                text = await self._transcribe_with_whisper_module(tmp_path)
            if not text:
                print("[VOICE-MSG] No se pudo transcribir.")
                return
            print(f"[VOICE-MSG] {message.author.display_name}: '{text}'")
            parsed = full_parse(text, require_activator=True)
            print(f"[VOICE-MSG] Parsed: {parsed}")
            if parsed["action"] == "ignored":
                await message.add_reaction("🤔")
                await message.reply(
                    "Escuché tu audio pero no detecté un comando. "
                    "Empieza con **\"Rodolfo\"**, por ejemplo: *\"Rodolfo pon despacito\"*",
                    delete_after=15,
                )
                return
            if parsed["action"] == "unknown":
                await message.add_reaction("❓")
                await message.reply(
                    f"Escuché: *\"{parsed.get('cmd', text[:50])}\"* pero no entendí el comando.",
                    delete_after=15,
                )
                return
            if parsed["action"] == "greet":
                await message.add_reaction("👋")
                return
            await message.add_reaction("🎵")
            guild = message.guild
            if guild:
                player = get_player(guild.id)
                channel = None
                vs = guild._voice_states.get(message.author.id)
                if vs and vs.channel:
                    channel = vs.channel
                else:
                    channel = await find_voice_channel(guild)
                if channel:
                    await player.connect(channel)
                await self._execute_action(parsed, message.author.display_name, message)
        except Exception as e:
            print(f"[VOICE-MSG] Error: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    async def _transcribe_voice_message(self, audio_path: str):
        try:
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: subprocess.run(
                ["whisper", audio_path,
                 "--model", WHISPER_MODEL,
                 "--language", "es",
                 "--output_format", "txt",
                 "--output_dir", os.path.dirname(audio_path)],
                capture_output=True, text=True, timeout=60,
            ))
            txt_path = os.path.splitext(audio_path)[0] + ".txt"
            if os.path.exists(txt_path):
                with open(txt_path, encoding="utf-8") as f:
                    text = f.read().strip().lower()
                try:
                    os.unlink(txt_path)
                except OSError:
                    pass
                return text
        except Exception as e:
            print(f"[VOICE-MSG] Error CLI whisper: {e}")
        return None

    async def _transcribe_with_whisper_module(self, audio_path: str):
        try:
            import whisper as wm
            loop  = asyncio.get_event_loop()
            model = await loop.run_in_executor(None, wm.load_model, WHISPER_MODEL)
            result = await loop.run_in_executor(
                None, lambda: model.transcribe(audio_path, language="es", fp16=False)
            )
            return result.get("text", "").strip().lower()
        except ImportError:
            print("[VOICE-MSG] Módulo whisper no instalado.")
        except Exception as e:
            print(f"[VOICE-MSG] Error whisper module: {e}")
        return None

    # ── Comandos de prefijo (!play, !skip, etc.) ───────────────────────────────

    @commands.command(name="play", aliases=["p"])
    async def cmd_play(self, ctx, *, query):
        if not ctx.author.voice:
            await ctx.send("Necesitas estar en un canal de voz.")
            return
        player = get_player(ctx.guild.id)
        await player.connect(ctx.author.voice.channel)
        tracks, started_now = await player.add(query)
        titles = ", ".join(t["title"] for t in tracks[:3])
        extra  = f" (+{len(tracks)-3})" if len(tracks) > 3 else ""
        prefix = "🎵 Sonando" if started_now else "📋 En cola"
        await ctx.send(f"{prefix}: {titles}{extra}")

    @commands.command(name="skip", aliases=["s"])
    async def cmd_skip(self, ctx):
        get_player(ctx.guild.id).skip()
        await ctx.send("⏭️ Skip.")

    @commands.command(name="stop")
    async def cmd_stop(self, ctx):
        get_player(ctx.guild.id).stop()
        await ctx.send("⏹️ Stop.")

    @commands.command(name="pause")
    async def cmd_pause(self, ctx):
        if get_player(ctx.guild.id).pause():
            await ctx.send("⏸️ Pausa.")

    @commands.command(name="resume", aliases=["r"])
    async def cmd_resume(self, ctx):
        if get_player(ctx.guild.id).resume():
            await ctx.send("▶️ Reanudando.")

    @commands.command(name="queue", aliases=["q"])
    async def cmd_queue(self, ctx):
        player = get_player(ctx.guild.id)
        msg = []
        if player.current:
            msg.append(f"**Ahora:** {player.current['title']}")
        if player.queue:
            msg.append("**Cola:**")
            for i, t in enumerate(list(player.queue)[:10], 1):
                msg.append(f"{i}. {t['title']}")
        await ctx.send("\n".join(msg) if msg else "Cola vacía.")

    @commands.command(name="leave", aliases=["dc"])
    async def cmd_leave(self, ctx):
        await get_player(ctx.guild.id).disconnect()
        await ctx.send("👋 Bye.")

    # ── Slash commands (/play, /skip, etc.) ───────────────────────────────────

    @discord.slash_command(name="play", description="Reproduce música o la agrega a la cola.", **_slash_guild_kwargs)
    async def slash_play(self, ctx, query: discord.Option(str, "Canción o URL")):
        if not ctx.author.voice:
            await ctx.respond("Necesitas estar en un canal de voz.", ephemeral=True)
            return
        await ctx.defer()
        player = get_player(ctx.guild.id)
        await player.connect(ctx.author.voice.channel)
        tracks, started_now = await player.add(query)
        titles = ", ".join(t["title"] for t in tracks[:3])
        extra  = f" (+{len(tracks)-3})" if len(tracks) > 3 else ""
        prefix = "🎵 Sonando" if started_now else "📋 En cola"
        await ctx.followup.send(f"{prefix}: {titles}{extra}")

    @discord.slash_command(name="skip", description="Salta a la siguiente canción.", **_slash_guild_kwargs)
    async def slash_skip(self, ctx):
        get_player(ctx.guild.id).skip()
        await ctx.respond("⏭️ Siguiente canción.")

    @discord.slash_command(name="pause", description="Pausa la música.", **_slash_guild_kwargs)
    async def slash_pause(self, ctx):
        if get_player(ctx.guild.id).pause():
            await ctx.respond("⏸️ Pausa.")
        else:
            await ctx.respond("No hay nada sonando.", ephemeral=True)

    @discord.slash_command(name="resume", description="Reanuda la música.", **_slash_guild_kwargs)
    async def slash_resume(self, ctx):
        if get_player(ctx.guild.id).resume():
            await ctx.respond("▶️ Reanudando.")
        else:
            await ctx.respond("No hay nada pausado.", ephemeral=True)

    @discord.slash_command(name="stop", description="Detiene la música y vacía la cola.", **_slash_guild_kwargs)
    async def slash_stop(self, ctx):
        get_player(ctx.guild.id).stop()
        await ctx.respond("⏹️ Música detenida.")

    @discord.slash_command(name="queue", description="Muestra la cola de reproducción.", **_slash_guild_kwargs)
    async def slash_queue(self, ctx):
        player = get_player(ctx.guild.id)
        msg = []
        if player.current:
            msg.append(f"**🎵 Sonando:** {player.current['title']}")
        if player.queue:
            msg.append("**📋 Cola:**")
            for i, t in enumerate(list(player.queue)[:10], 1):
                msg.append(f"`{i}.` {t['title']}")
            if len(player.queue) > 10:
                msg.append(f"_...y {len(player.queue)-10} más_")
        await ctx.respond("\n".join(msg) if msg else "Cola vacía.")

    @discord.slash_command(name="now", description="Muestra la canción actual.", **_slash_guild_kwargs)
    async def slash_now(self, ctx):
        player = get_player(ctx.guild.id)
        if player.current:
            await ctx.respond(f"🎵 **{player.current['title']}**")
        else:
            await ctx.respond("No hay música sonando.", ephemeral=True)

    @discord.slash_command(name="leave", description="Desconecta el bot del canal.", **_slash_guild_kwargs)
    async def slash_leave(self, ctx):
        await get_player(ctx.guild.id).disconnect()
        await ctx.respond("👋 Bye.")


# ─── Registro del módulo ──────────────────────────────────────────────────────

def setup(bot: commands.Bot):
    bot.add_cog(MusicCog(bot))
    print("[MÓDULO] Música cargada.")
