"""
sink.py — Voice receive: captura audio del canal de voz y lo transcribe.

⚠️  ESTADO (2026): Discord DAVE (E2E encryption) rompe voice receive en py-cord.
    Issue: https://github.com/Pycord-Development/pycord/issues/3139
    Cuando lo arreglen, este código funcionará tal cual.
    Mientras tanto los amigos usan /play, !play o notas de voz.
"""

import asyncio

import discord

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False

import os
VAD_AMPLITUDE_THRESHOLD = int(os.getenv("VAD_AMPLITUDE_THRESHOLD", "500"))
VAD_SILENCE_MS          = int(os.getenv("VAD_SILENCE_MS",          "700"))
VAD_MIN_SPEECH_MS       = int(os.getenv("VAD_MIN_SPEECH_MS",       "400"))


class LiveTranscriptionSink(discord.sinks.Sink):
    """Detecta cuando un usuario termina de hablar y dispara un callback async."""

    __sink_listeners__ = []
    __sink_event__     = ""

    def __init__(self, on_speech, owner_id: int, bot_id: int, bot_loop=None):
        super().__init__()
        self.on_speech      = on_speech
        self.owner_id       = owner_id
        self.bot_id         = bot_id
        self._loop          = bot_loop
        self.user_buffers   = {}
        self.user_silence   = {}
        self.SILENCE_FRAMES = max(5, VAD_SILENCE_MS // 20)
        self.MIN_BYTES      = max(1, VAD_MIN_SPEECH_MS // 20) * 3840

    def write(self, data, user):
        if user is None or user == self.owner_id or user == self.bot_id:
            return
        if not HAS_NUMPY:
            return

        pcm       = data.pcm
        samples   = np.frombuffer(pcm, dtype=np.int16)
        if len(samples) == 0:
            return
        amplitude = float(np.abs(samples).mean())
        is_silent = amplitude < VAD_AMPLITUDE_THRESHOLD

        if user not in self.user_buffers:
            self.user_buffers[user] = bytearray()
            self.user_silence[user] = 0

        if is_silent:
            self.user_silence[user] += 1
            if (len(self.user_buffers[user]) > 0
                    and self.user_silence[user] >= self.SILENCE_FRAMES):
                audio = bytes(self.user_buffers[user])
                self.user_buffers[user] = bytearray()
                self.user_silence[user] = 0
                if len(audio) >= self.MIN_BYTES and self._loop:
                    asyncio.run_coroutine_threadsafe(
                        self.on_speech(audio, user), self._loop
                    )
            elif len(self.user_buffers[user]) > 0 and self.user_silence[user] <= 5:
                self.user_buffers[user].extend(pcm)
        else:
            self.user_silence[user] = 0
            self.user_buffers[user].extend(pcm)


async def transcribe_pcm(pcm_bytes: bytes) -> str | None:
    """Convierte PCM 48kHz int16 stereo → texto usando Google STT."""
    if not HAS_NUMPY or not HAS_SR:
        return None
    try:
        audio      = np.frombuffer(pcm_bytes, dtype=np.int16)
        audio      = audio.reshape(-1, 2).mean(axis=1).astype(np.int16)
        recognizer = sr.Recognizer()
        audio_data = sr.AudioData(audio.tobytes(), sample_rate=48000, sample_width=2)
        loop       = asyncio.get_event_loop()
        text       = await loop.run_in_executor(
            None,
            lambda: recognizer.recognize_google(audio_data, language="es-ES"),
        )
        return text.lower().strip()
    except sr.UnknownValueError:
        return None
    except sr.RequestError as e:
        print(f"[VOICE-IN] Google STT error: {e}")
        return None
    except Exception as e:
        print(f"[VOICE-IN] Error transcribiendo: {e}")
        return None
