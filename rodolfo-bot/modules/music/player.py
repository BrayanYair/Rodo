"""
player.py — MusicPlayer: cola, reproducción, TTS, pausa/reanudación.
Un MusicPlayer por servidor de Discord (guild_id).
"""

import os
import time
import asyncio
import tempfile
from collections import deque

import discord
import edge_tts
from dotenv import load_dotenv

from .search import (yt_search, resolve_query, resolve_playlist_lazy,
                      resolve_by_type, resolve_user_saved_tracks,
                      PREFETCH_AHEAD, SPOTIFY_URL_RE)
from .cache import mark_stream_invalid, extract_track_key, log_stat, _get_track_lock

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
        self._lazy_queue        = []     # queries pendientes de playlist lazy (str)
        self._prefetching       = False  # evita fetches concurrentes del lazy queue
        self._user_key          = "owner"

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

    # ─── Lazy playlist prefetch ────────────────────────────────────────────────

    async def _maybe_prefetch(self):
        """Resuelve el siguiente item del lazy queue si la cola está casi vacía."""
        if self._prefetching or not self._lazy_queue:
            return
        if len(self.queue) >= PREFETCH_AHEAD:
            return
        self._prefetching = True
        query = self._lazy_queue.pop(0)
        try:
            from .search import _log_query, resolve_query
            tracks = await resolve_query(query, user_key=self._user_key)
            if tracks:
                track = tracks[0]
                self.queue.append(track)
                remaining = len(self._lazy_queue)
                print(f"[PREFETCH] '{track['title'][:50]}' — {remaining} pendientes")
            # Si todavía hay espacio en la cola, traer otra
            if len(self.queue) < PREFETCH_AHEAD and self._lazy_queue:
                asyncio.ensure_future(self._maybe_prefetch())
        except Exception as e:
            print(f"[PREFETCH] Error en '{query}': {e}")
        finally:
            self._prefetching = False

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
        self._lazy_queue.clear()
        self.current = None

    # ─── Reproducción ──────────────────────────────────────────────────────────

    async def _play_track(self, track: dict, start_time: float = 0.0, _retry: bool = False):
        """
        Reproduce un track. Si el after() detecta error de stream (URL inválida),
        marca el track como inválido en cache, re-extrae la URL y reintenta UNA vez.
        """
        # Capturar el event loop (siempre corremos en contexto async aquí)
        self._loop = asyncio.get_running_loop()
        self.current = track

        # ── L3 Refresh por TTL: re-extraer si la URL tiene >4 horas ──────────
        _age = time.time() - track.get("_resolved_at", 0)
        if start_time == 0.0 and not _retry and track.get("webpage_url") and _age > 3600 * 4:
            print(f"[PLAYER] URL de '{track['title'][:40]}' tiene {_age/3600:.1f}h — re-fetching")
            try:
                track_key = extract_track_key(track.get("webpage_url", ""))
                lock = _get_track_lock(track_key)
                async with lock:
                    fresh = await yt_search(track["webpage_url"], log=False)
                    track["url"] = fresh["url"]
                    track["_resolved_at"] = time.time()
                log_stat("STREAM_REFRESH", track.get("title", ""), "L3", 0)
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
                error_str = str(error).lower()
                # Clasificar: ¿es un error de stream inválido (403, 410, network)?
                is_stream_error = any(x in error_str for x in (
                    "403", "410", "429", "403 forbidden", "unavailable",
                    "connection reset", "epipe", "broken pipe",
                ))
                if is_stream_error and not _retry:
                    print(f"[PLAYER] Error de stream detectado: {error} — marcando inválido y reintentando")
                    asyncio.run_coroutine_threadsafe(
                        self._refresh_and_retry(track, start_time), self._loop
                    )
                    return
                print(f"[PLAYER] Error post-track (no recuperable): {error}")
            asyncio.run_coroutine_threadsafe(self._on_finished(), self._loop)

        self.voice_client.play(source, after=after)
        print(f"[REPRODUCIENDO]{' (reintento)' if _retry else ''} {track['title']}") 

    async def _refresh_and_retry(self, track: dict, start_time: float):
        """
        Llamado cuando after() detectó un error de stream (HTTP 403/429/firma inválida).

        Flujo:
          1. Marca el track como inválido en la caché (stream_invalid=1, stream_url=NULL)
          2. Adquiere el lock por track_key (evita doble-refresh si dos guilds fallan a la vez)
          3. Re-extrae la URL directamente desde YouTube
          4. Actualiza la caché con la URL fresca
          5. Reintenta la reproducción con _retry=True (evita recursión infinita)
          6. Si el re-fetch también falla, avanza a la siguiente canción normalmente
        """
        webpage_url = track.get("webpage_url", "")
        track_key   = extract_track_key(webpage_url)

        # 1. Invalidar en caché antes de pedir el lock
        if track_key:
            mark_stream_invalid(track_key)
            log_stat("PLAYBACK_FAIL_REFRESH", track.get("title", ""), "L3_FORCE", 0)

        try:
            lock = _get_track_lock(track_key) if track_key else None
            ctx = lock if lock else asyncio.nullcontext()
            async with ctx:
                print(f"[PLAYER] Re-extrayendo URL por fallo de stream: '{track['title'][:50]}'")
                fresh = await yt_search(webpage_url, log=False)
                track["url"] = fresh["url"]
                track["_resolved_at"] = time.time()

                # Actualizar caché con la URL fresca
                if track_key:
                    from .cache import refresh_stream_url
                    expires = int(track["_resolved_at"] + 4 * 3600)
                    refresh_stream_url(track_key, fresh["url"], expires)

            # 5. Reintentar reproducción (una sola vez, _retry=True)
            await self._play_track(track, start_time=start_time, _retry=True)

        except Exception as e:
            print(f"[PLAYER] Re-extracción fallida también: {e} — avanzando a siguiente")
            await self._on_finished()

    async def _on_finished(self):
        # Si el bot fue desconectado (ej: "pasemos a mi PC"), limpiar estado y no reproducir.
        if not self.voice_client or not self.voice_client.is_connected():
            self._tts_pending       = None
            self._interrupted_track = None
            self._interrupted_time  = 0.0
            self.current            = None
            return

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
                next_track = self.queue.popleft()
                # Si la cola quedó baja, traer otra del lazy queue mientras suena esta
                if len(self.queue) < PREFETCH_AHEAD and self._lazy_queue:
                    asyncio.ensure_future(self._maybe_prefetch())
                await self._play_track(next_track)
            else:
                self.current = None
        except Exception as e:
            print(f"[PLAYER] Error en _on_finished, recuperando: {e}")
            self._tts_pending       = None
            self._interrupted_track = None
            self._interrupted_time  = 0.0
            # Verificar conexión antes de reintentar
            if self.queue and self.voice_client and self.voice_client.is_connected():
                try:
                    next_track = self.queue.popleft()
                    if len(self.queue) < PREFETCH_AHEAD and self._lazy_queue:
                        asyncio.ensure_future(self._maybe_prefetch())
                    await self._play_track(next_track)
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

    async def add(self, query: str, shuffle: bool = False,
                  spotify_type: str | None = None,
                  user_token: str | None = None,
                  user_key: str = "owner"):
        """
        Agrega una canción, álbum, playlist, artista o biblioteca personal a la cola.

        spotify_type: "album" | "playlist" | "artist" | "saved_tracks" | None
          - None          → búsqueda libre (texto o URL directa)
          - saved_tracks  → canciones guardadas del usuario (requiere user_token)
          - otros         → búsqueda por tipo en Spotify + lazy streaming
        user_token: token de Spotify personal del usuario (para saved_tracks y futuras
                    búsquedas en biblioteca privada)
        user_key: clave identificadora del usuario para asociar sus gustos en caché SQLite
        """
        import time
        t0 = time.time()
        self._user_key = user_key
        print(f"[TIMING] Buscando: '{query[:50]}' (type={spotify_type or 'free'}, user_key={user_key})")

        pending: list[str] = []

        if spotify_type == "saved_tracks":
            if not user_token:
                print("[PLAYER] saved_tracks solicitado pero sin user_token — ignorando")
                return [], False
            tracks, pending = await resolve_user_saved_tracks(user_token, shuffle=shuffle)
            print(f"[TIMING] resolve_user_saved_tracks en {time.time()-t0:.2f}s "
                  f"— {len(tracks)} inmediatas, {len(pending)} pendientes")
        elif spotify_type in ("album", "playlist", "artist"):
            # Búsqueda inteligente por tipo — lazy streaming
            tracks, pending = await resolve_by_type(query, spotify_type, shuffle=shuffle)
            print(f"[TIMING] resolve_by_type en {time.time()-t0:.2f}s "
                  f"— {len(tracks)} inmediatas, {len(pending)} pendientes")
        else:
            # Detectar URLs de Spotify (playlist/album pegadas directamente)
            m = SPOTIFY_URL_RE.search(query)
            is_url_list = m and m.group(1) in ("playlist", "album")
            if is_url_list:
                tracks, pending = await resolve_playlist_lazy(query, shuffle=shuffle)
                print(f"[TIMING] URL lazy en {time.time()-t0:.2f}s "
                      f"— {len(tracks)} inmediatas, {len(pending)} pendientes")
            else:
                tracks  = await resolve_query(query, user_key=user_key)
                print(f"[TIMING] Búsqueda en {time.time()-t0:.2f}s "
                      f"→ '{tracks[0]['title'][:50] if tracks else '?'}'")

        self._lazy_queue.extend(pending)

        # voice_busy = bot conectado Y reproduciendo/pausado activamente
        voice_busy = (
            self.voice_client is not None
            and self.voice_client.is_connected()
            and (self.voice_client.is_playing() or self.voice_client.is_paused())
        )
        should_start = not voice_busy
        if should_start:
            self.current = None
        for t in tracks:
            self.queue.append(t)
        if should_start and self.queue:
            if self._lazy_queue:
                asyncio.ensure_future(self._maybe_prefetch())
            await self._play_track(self.queue.popleft())
        t1 = time.time()
        started_now = should_start
        print(f"[ADD] started={started_now} queue={len(self.queue)} lazy={len(self._lazy_queue)} "
              f"total={t1-t0:.2f}s")
        return tracks, started_now

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
        self._lazy_queue.clear()
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
        """Limpia cola y lazy queue sin detener lo que suena. Devuelve cuántas se eliminaron."""
        n = len(self.queue) + len(self._lazy_queue)
        self.queue.clear()
        self._lazy_queue.clear()
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
