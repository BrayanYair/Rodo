"""
player.py — MusicPlayer: cola, reproducción, TTS, pausa/reanudación.
Un MusicPlayer por servidor de Discord (guild_id).
"""

import os
import asyncio
import tempfile
from collections import deque

import discord
import edge_tts
from dotenv import load_dotenv

from .search import yt_search, resolve_query

load_dotenv()

TTS_VOICE    = os.getenv("TTS_VOICE", "es-ES-ElviraNeural")
FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 "
        "-reconnect_delay_max 5 -reconnect_on_network_error 1"
    ),
    "options": "-vn",
}


# ─── Audio con posición absoluta (para reanudar post-TTS) ────────────────────
class ResumableFFmpegAudio(discord.FFmpegPCMAudio):
    def __init__(self, source_url, *args, start_offset: float = 0.0, **kwargs):
        super().__init__(source_url, *args, **kwargs)
        self.frames_read  = 0
        self.start_offset = start_offset

    def read(self):
        data = super().read()
        if data:
            self.frames_read += 1
        return data

    @property
    def absolute_position(self) -> float:
        """Segundos transcurridos del track original, sumando el offset de inicio."""
        return self.start_offset + self.frames_read * 0.020


# ─── Reproductor por servidor ─────────────────────────────────────────────────
class MusicPlayer:
    def __init__(self, guild_id: int):
        self.guild_id           = guild_id
        self.queue              = deque()
        self.current            = None
        self.voice_client       = None
        self.volume             = 0.7
        self._tts_pending       = None   # path MP3 de TTS pendiente
        self._interrupted_track = None   # track pausado por TTS
        self._interrupted_time  = 0.0
        self.connect_lock       = asyncio.Lock()
        self._loop              = None   # event loop, capturado en primer play

    # ─── Conexión ───────────────────────────────────────────────────────────────

    async def connect(self, channel):
        async with self.connect_lock:
            if self.voice_client:
                if self.voice_client.is_connected():
                    if self.voice_client.channel.id != channel.id:
                        try:
                            await asyncio.wait_for(
                                self.voice_client.move_to(channel), timeout=5.0
                            )
                        except Exception as e:
                            print(f"[PLAYER] Error al mover bot, reconectando: {e}")
                            try:
                                await self.voice_client.disconnect()
                            except Exception:
                                pass
                            self.voice_client = None
                    if self.voice_client:
                        return
                else:
                    try:
                        await self.voice_client.disconnect()
                    except Exception:
                        pass
                    self.voice_client = None

            print(f"[PLAYER] Conectando al canal: {channel.name}")
            self.voice_client = await channel.connect()

    async def disconnect(self):
        if self.voice_client and self.voice_client.is_connected():
            try:
                if getattr(self.voice_client, "_listen_started", False):
                    self.voice_client.stop_recording()
            except Exception:
                pass
            await self.voice_client.disconnect()
        self.voice_client = None
        self.queue.clear()
        self.current = None

    # ─── Reproducción ──────────────────────────────────────────────────────────

    async def _play_track(self, track: dict, start_time: float = 0.0):
        # Capturar el event loop (siempre corremos en contexto async aquí)
        self._loop = asyncio.get_running_loop()
        self.current = track

        # Re-extraer URL fresca al empezar desde el principio (evita error -138)
        if start_time == 0.0 and track.get("webpage_url"):
            try:
                fresh = await yt_search(track["webpage_url"], log=False)
                track["url"] = fresh["url"]
            except Exception as e:
                print(f"[PLAYER] Re-fetch falló, usando URL cached: {e}")

        opts = FFMPEG_OPTIONS.copy()
        if start_time > 0:
            before = opts.get("before_options", "")
            opts["before_options"] = f"-ss {start_time:.3f} {before}".strip()
            print(f"[PLAYER] Reanudando '{track['title']}' desde {start_time:.2f}s")

        source = ResumableFFmpegAudio(track["url"], start_offset=start_time, **opts)
        source = discord.PCMVolumeTransformer(source, volume=self.volume)

        def after(error):
            if error:
                print(f"[PLAYER] Error post-track: {error}")
            asyncio.run_coroutine_threadsafe(self._on_finished(), self._loop)

        self.voice_client.play(source, after=after)
        print(f"[REPRODUCIENDO] {track['title']}")

    async def _on_finished(self):
        try:
            if self._tts_pending:
                tts_path = self._tts_pending
                self._tts_pending = None
                await self._play_tts(tts_path)
                return
            if self._interrupted_track:
                track      = self._interrupted_track
                start_time = self._interrupted_time
                self._interrupted_track = None
                self._interrupted_time  = 0.0
                await self._play_track(track, start_time=start_time)
                return
            if self.queue:
                await self._play_track(self.queue.popleft())
            else:
                self.current = None
        except Exception as e:
            print(f"[PLAYER] Error en _on_finished, recuperando: {e}")
            self._tts_pending       = None
            self._interrupted_track = None
            self._interrupted_time  = 0.0
            if self.queue:
                try:
                    await self._play_track(self.queue.popleft())
                except Exception as e2:
                    print(f"[PLAYER] Error de recuperación: {e2}")
                    self.current = None
            else:
                self.current = None

    async def _play_tts(self, tts_path: str):
        source = discord.FFmpegPCMAudio(tts_path)
        source = discord.PCMVolumeTransformer(source, volume=1.0)

        def after(error):
            try:
                os.unlink(tts_path)
            except OSError:
                pass
            if error:
                print(f"[TTS] Error: {error}")
            asyncio.run_coroutine_threadsafe(self._on_finished(), self._loop)

        self.voice_client.play(source, after=after)
        print("[TTS] Hablando en el canal de voz...")

    async def say(self, text: str) -> bool:
        """Genera TTS y lo reproduce. Si hay música la pausa y la reanuda después."""
        if not self.voice_client or not self.voice_client.is_connected():
            return False
        # Capturar loop si aún no lo tenemos (say puede ser el primer call async)
        if not self._loop:
            self._loop = asyncio.get_running_loop()

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
            await communicate.save(tmp_path)
        except Exception as e:
            print(f"[TTS] Error generando: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False

        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self._tts_pending = tmp_path
            if self.current and not self._interrupted_track:
                self._interrupted_track = self.current
                elapsed = 0.0
                if self.voice_client.source:
                    src = self.voice_client.source
                    if isinstance(src, discord.PCMVolumeTransformer):
                        src = src.original
                    if hasattr(src, "absolute_position"):
                        elapsed = src.absolute_position
                    elif hasattr(src, "frames_read"):
                        elapsed = src.frames_read * 0.020
                self._interrupted_time = elapsed
                print(f"[TTS] Interrumpiendo '{self.current['title']}' en {elapsed:.2f}s")
            self.voice_client.stop()
        else:
            await self._play_tts(tmp_path)
        return True

    async def add(self, query: str):
        tracks = await resolve_query(query)
        voice_busy = (
            self.voice_client is not None
            and self.voice_client.is_connected()
            and (self.voice_client.is_playing() or self.voice_client.is_paused())
        )
        was_idle = not voice_busy and len(self.queue) == 0
        if was_idle:
            self.current = None
        for t in tracks:
            self.queue.append(t)
        if was_idle and self.queue:
            await self._play_track(self.queue.popleft())
        print(f"[ADD] query='{query[:40]}' was_idle={was_idle} queue={len(self.queue)}")
        return tracks, was_idle

    # ─── Controles ─────────────────────────────────────────────────────────────

    def skip(self):
        self._interrupted_track = None
        self._interrupted_time  = 0.0
        self._tts_pending       = None
        if self.voice_client and (self.is_playing() or self.is_paused()):
            self.voice_client.stop()
        elif self.current and not self.queue:
            self.current = None

    def stop(self):
        self.queue.clear()
        self._interrupted_track = None
        self._interrupted_time  = 0.0
        self._tts_pending       = None
        if self.voice_client and (self.is_playing() or self.is_paused()):
            self.voice_client.stop()
        self.current = None

    def pause(self) -> bool:
        if self.is_playing():
            self.voice_client.pause()
            return True
        return False

    def resume(self) -> bool:
        if self.is_paused():
            self.voice_client.resume()
            return True
        return False

    def set_volume(self, vol: float):
        self.volume = max(0.0, min(1.0, vol))
        if self.voice_client and self.voice_client.source:
            try:
                self.voice_client.source.volume = self.volume
            except AttributeError:
                pass

    def clear_queue(self) -> int:
        """Limpia la cola sin detener lo que suena. Devuelve cuántas se eliminaron."""
        n = len(self.queue)
        self.queue.clear()
        return n

    def remove_last(self):
        """Quita la última canción de la cola. Devuelve el título o None."""
        if not self.queue:
            return None
        return self.queue.pop().get("title")

    def is_playing(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_playing()

    def is_paused(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_paused()


# ─── Registry de players por guild ───────────────────────────────────────────
_players: dict[int, MusicPlayer] = {}

def get_player(guild_id: int) -> MusicPlayer:
    if guild_id not in _players:
        _players[guild_id] = MusicPlayer(guild_id)
    return _players[guild_id]
