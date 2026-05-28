"""
orchestrator.py — Orquestador central de Rodo
=============================================
Centraliza el estado de sesión y las decisiones de routing.

HOY  → reglas determinísticas (if/elif)
FUTURO → pluggable con LLM (Claude API)

Para pasar a IA, basta reemplazar decide() con decide_ai():

    import anthropic

    SYSTEM_PROMPT = \"\"\"
    Sos Rodo, asistente de voz personal.
    Estado actual: {state}
    Comandos disponibles:
      - discord      → enviar al bot de Discord
      - local        → reproducir en Spotify/YouTube local
      - local_media  → tecla multimedia de Windows
      - ask          → preguntar al usuario primero
      - oauth        → iniciar flujo OAuth de Spotify
      - ignore       → no hacer nada
    Respondé SOLO con JSON: {{"handler": "...", "intent": "...", "params": {{}}}}
    \"\"\"

    def decide_ai(self, raw_text: str) -> Action:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=256,
            system=SYSTEM_PROMPT.format(state=self.state.as_dict()),
            messages=[{"role": "user", "content": raw_text}],
        )
        return _parse_ai_action(msg.content[0].text)
"""

from __future__ import annotations

import difflib
import threading
from dataclasses import dataclass, field
from typing import Optional, Set, Dict, Any


# ─── Resultado de decisión ────────────────────────────────────────────────────

@dataclass
class Action:
    """
    Decisión del orquestador: qué debe hacer amigo.py.

    handler:
      "discord"      → enviar al bot de Discord vía /command
      "local"        → reproducir en local (Spotify URI o YouTube)
      "local_media"  → emitir tecla multimedia de Windows
      "ask"          → preguntar al usuario (¿Discord o local?)
      "oauth"        → iniciar flujo OAuth de Spotify
      "ignore"       → no hacer nada
    """
    handler: str
    text:    Optional[str]      = None   # texto crudo del comando
    intent:  Optional[str]      = None   # intent parseado (play_music, skip_music, …)
    words:   Optional[Set[str]] = None   # palabras para media key routing
    params:  Dict[str, Any]     = field(default_factory=dict)


# ─── Estado de sesión ─────────────────────────────────────────────────────────

class OrchestratorState:
    """
    Estado mutable completo de la sesión de Rodo.

    Soporta acceso tipo dict para compatibilidad con el código existente:
        state["discord_mode"]        → getattr
        state["discord_mode"] = True → setattr
        state.get("discord_mode")    → getattr con default
    """

    __slots__ = (
        "discord_mode", "spotify_token", "spotify_linked", "voice_channel",
        "current_track", "is_playing", "volume",
        "announced_exit", "asking",
    )

    def __init__(self):
        # Modo de reproducción: None=sin decidir, True=Discord, False=local
        self.discord_mode:   Optional[bool] = None
        # Token OAuth personal de Spotify del usuario (None si no vinculó)
        self.spotify_token:  Optional[str]  = None
        self.spotify_linked: bool           = False
        # Canal de Discord donde está el usuario actualmente
        self.voice_channel:  Optional[str]  = None
        # Canción sonando en Discord (actualizada por /status)
        self.current_track:  Optional[str]  = None
        self.is_playing:     bool           = False
        self.volume:         float          = 0.7
        # Evita anunciar "saliste de Discord" más de una vez por sesión de canal
        self.announced_exit: bool           = False
        # True mientras hay una pregunta yes/no activa (evita duplicar)
        self.asking:         bool           = False

    # ── Acceso tipo dict ─────────────────────────────────────────────────
    def __getitem__(self, key: str):
        return getattr(self, key)

    def __setitem__(self, key: str, value):
        setattr(self, key, value)

    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def as_dict(self) -> dict:
        """
        Snapshot del estado — útil para logs y como contexto para el LLM.

        Ejemplo de uso en decide_ai():
            system = PROMPT.format(state=self.state.as_dict())
        """
        return {
            "discord_mode":  self.discord_mode,
            "has_spotify":   bool(self.spotify_token or self.spotify_linked),
            "voice_channel": self.voice_channel,
            "current_track": self.current_track,
            "is_playing":    self.is_playing,
            "volume":        self.volume,
        }

    def __repr__(self):
        return (
            f"OrchestratorState("
            f"mode={self.discord_mode}, "
            f"spotify={'✓' if self.spotify_token else '✗'}, "
            f"track={self.current_track!r})"
        )


# ─── Orquestador ──────────────────────────────────────────────────────────────

class RodoOrchestrator:
    """
    Cerebro central de Rodo.

    Responsabilidades
    -----------------
    1. Mantener el estado de sesión unificado (OrchestratorState)
    2. Decidir a qué handler enrutar cada comando (decide)
    3. Exponer eventos del canal de voz de Discord (on_enter_voice / on_exit_voice)
    4. Buscar en la biblioteca personal de Spotify cuando el usuario tiene token

    Extensión con IA (futuro)
    -------------------------
    Reemplazar o decorar decide() con decide_ai() que llama a Claude API.
    El estado ya está preparado en as_dict() para usarlo como contexto.
    """

    # ── Vocabulario de routing ────────────────────────────────────────────
    LOCAL_CTRL = {
        "para", "pausa", "pausar", "stop", "detener", "detiene",
        "siguiente", "salta", "saltar", "skip", "next", "pasa",
        "sigue", "resume", "continua", "continuar", "reanuda", "play",
        "sube", "subir", "baja", "bajar", "silencia", "mute", "silencio",
        "anterior", "atras", "volver", "prev",
    }
    MUSIC_PLAY = {"play_music", "queue_music"}
    MUSIC_CTRL = {
        "skip_music", "stop_music", "pause_music", "resume_music",
        "disconnect_music", "clear_queue", "remove_last", "music_status",
    }
    ALL_MUSIC = MUSIC_PLAY | MUSIC_CTRL

    def __init__(self):
        self.state = OrchestratorState()
        self._lock = threading.Lock()

    # ── Propiedades ──────────────────────────────────────────────────────

    @property
    def discord_mode(self) -> Optional[bool]:
        return self.state.discord_mode

    @property
    def spotify_token(self) -> Optional[str]:
        return self.state.spotify_token

    @property
    def has_spotify(self) -> bool:
        return bool(self.state.spotify_token or self.state.spotify_linked)

    # ── Mutadores de estado ──────────────────────────────────────────────

    def set_discord_mode(self, mode: Optional[bool], reason: str = ""):
        with self._lock:
            self.state.discord_mode = mode
        if reason:
            print(f"[ORCH] discord_mode={mode} — {reason}", flush=True)

    def set_spotify_token(self, token: Optional[str]):
        with self._lock:
            self.state.spotify_token = token
        print(f"[ORCH] Spotify {'vinculado ✓' if token else 'desvinculado'}", flush=True)

    def set_spotify_linked(self, linked: bool):
        with self._lock:
            self.state.spotify_linked = bool(linked)
        print(f"[ORCH] Spotify {'vinculado' if linked else 'desvinculado'}", flush=True)

    def set_current_track(self, title: Optional[str], is_playing: bool = True):
        self.state.current_track = title
        self.state.is_playing    = is_playing

    # ── Eventos de canal de voz ──────────────────────────────────────────

    def on_enter_voice(self, channel: Optional[str] = None) -> bool:
        """
        Llamar cuando el usuario entra a un canal de Discord.
        Retorna True si hay que anunciar el cambio al usuario.
        """
        self.state.announced_exit = False
        self.state.voice_channel  = channel
        if self.state.discord_mode is False:
            with self._lock:
                self.state.discord_mode = None
            print("[ORCH] Entró a Discord desde modo local → reseteando", flush=True)
            return True   # anunciar: "Volviste a Discord. Decí qué querés escuchar."
        return False

    def on_exit_voice(self) -> bool:
        """
        Llamar cuando el usuario sale de un canal de Discord.
        Retorna True si hay que anunciar el cambio al usuario.
        """
        self.state.voice_channel = None
        if self.state.discord_mode is True and not self.state.announced_exit:
            with self._lock:
                self.state.discord_mode  = False
                self.state.announced_exit = True
            print("[ORCH] Salió de Discord → modo local", flush=True)
            return True   # anunciar: "Saliste de Discord. Cambié a modo local."
        return False

    # ── Decisión de routing ──────────────────────────────────────────────

    def decide(self,
               norm_cmd: str,
               norm_words: set,
               raw_text: str,
               parsed_intent: Optional[str] = None) -> Action:
        """
        Reglas de routing determinísticas.

        Este método es el punto de extensión para IA.
        Para usar LLM, sobreescribir con decide_ai() que:
          1. Serializa self.state.as_dict() como contexto del sistema
          2. Envía raw_text como mensaje del usuario
          3. Parsea la respuesta JSON del LLM como Action
        """
        mode = self.state.discord_mode

        # 1. Control local de medios ─────────────────────────────────────
        #    Intercepta siempre en modo local (para/siguiente/volumen…)
        ctrl_hit = norm_words & self.LOCAL_CTRL
        if mode is False and ctrl_hit:
            return Action("local_media", words=ctrl_hit, intent=parsed_intent)

        # 2. Controles de música ─────────────────────────────────────────
        #    skip/stop/pause/resume → local_media en modo local, Discord en el resto
        if parsed_intent in self.MUSIC_CTRL:
            if mode is False:
                return Action("local_media", intent=parsed_intent, words=norm_words)
            return Action("discord", text=raw_text, intent=parsed_intent)

        # 3. Reproducción (play / queue) ─────────────────────────────────
        #    Routing principal según el modo
        if parsed_intent in self.MUSIC_PLAY:
            explicit_local = any(p in norm_cmd for p in (
                "mis parlantes", "mis altavoces", "mi pc",
                "a local", "al local", "en local",
            )) or bool(norm_words & {"aqui", "aca"})
            explicit_discord = "discord" in norm_cmd or "discor" in norm_cmd
            if explicit_local:
                return Action("local", text=raw_text, intent=parsed_intent)
            if explicit_discord:
                return Action("discord", text=raw_text, intent=parsed_intent)
            if mode is True:
                return Action("discord", text=raw_text, intent=parsed_intent)
            elif mode is False:
                return Action("local", text=raw_text, intent=parsed_intent)
            else:
                return Action("ask", text=raw_text, intent=parsed_intent)

        # 4. Vincular Spotify personal ────────────────────────────────────
        if parsed_intent == "link_spotify":
            return Action("oauth", intent="link_spotify")

        # 5. Cualquier otro intent conocido → bot de Discord ─────────────
        if parsed_intent and parsed_intent not in ("unknown", "ignored", "greet"):
            return Action("discord", text=raw_text, intent=parsed_intent)

        return Action("ignore")

    # ── Búsqueda en biblioteca personal de Spotify ───────────────────────

    def search_personal_library(self,
                                 query: str,
                                 spotify_type: Optional[str] = None,
                                 max_items: int = 50) -> Optional[dict]:
        """
        Busca en la biblioteca personal del usuario (playlists + álbumes guardados).

        Requiere que state.spotify_token esté seteado.
        Retorna: {"uri": "spotify:...", "title": "...", "type": "playlist"|"album"}
        o None si no se encontró o no hay token.

        Uso desde amigo.py (modo local):
            result = orchestrator.search_personal_library(query, spotify_type)
            if result:
                webbrowser.open(result["uri"])
        """
        token = self.state.spotify_token
        if not token:
            return None

        try:
            import spotipy  # type: ignore
            user_sp = spotipy.Spotify(auth=token)
        except Exception as e:
            print(f"[ORCH] Error conectando a Spotify personal: {e}", flush=True)
            return None

        q_lower    = query.lower()
        candidates = []  # (score, uri, title, type)

        try:
            # Playlists del usuario (propias y seguidas)
            if spotify_type in (None, "playlist", "album"):
                result = user_sp.current_user_playlists(limit=min(max_items, 50))
                for pl in (result.get("items") or []):
                    if pl:
                        score = self._name_score(q_lower, pl["name"])
                        candidates.append((score, pl["uri"], pl["name"], "playlist"))

            # Álbumes guardados
            if spotify_type in (None, "album"):
                result = user_sp.current_user_saved_albums(limit=min(max_items, 50))
                for item in (result.get("items") or []):
                    alb = (item or {}).get("album", {})
                    if alb:
                        name   = alb["name"]
                        artist = alb["artists"][0]["name"] if alb.get("artists") else ""
                        title  = f"{name} — {artist}" if artist else name
                        score  = self._name_score(q_lower, name)
                        candidates.append((score, alb["uri"], title, "album"))

        except Exception as e:
            print(f"[ORCH] Error buscando biblioteca personal: {e}", flush=True)
            return None

        if not candidates:
            return None

        best = max(candidates, key=lambda c: c[0])
        if best[0] < 0.4:   # umbral mínimo — evita falsos positivos
            return None

        print(
            f"[ORCH] Biblioteca personal: '{query}' → '{best[2]}' "
            f"({best[3]}, score={best[0]:.2f})",
            flush=True,
        )
        return {"uri": best[1], "title": best[2], "type": best[3]}

    @staticmethod
    def _name_score(query: str, name: str) -> float:
        """Similitud entre query y nombre. Rango 0.0–2.5."""
        n = name.lower()
        q = query.lower()
        if q in n:
            return 1.5 + difflib.SequenceMatcher(None, q, n).ratio()
        if n.startswith(q):
            return 1.2 + difflib.SequenceMatcher(None, q, n).ratio()
        if n in q:
            return 1.0 + difflib.SequenceMatcher(None, q, n).ratio()
        return difflib.SequenceMatcher(None, q, n).ratio()

    def __repr__(self):
        return f"RodoOrchestrator({self.state})"


# ─── Instancia global ─────────────────────────────────────────────────────────
# amigo.py importa este singleton:
#   from orchestrator import orchestrator
orchestrator = RodoOrchestrator()
