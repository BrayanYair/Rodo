import time
import logging
import re
import functools
from modules.parser.normalizer import normalize, tokenize, strip_fillers, _detect_content_type
from modules.parser.stt_corrections import fix_common_stt_errors
from modules.parser.fuzzy import strip_activator
from modules.parser.base_intent import IntentResult

# Intents
from modules.parser.intents.stop_intent import StopIntent
from modules.parser.intents.pause_intent import PauseIntent
from modules.parser.intents.skip_intent import SkipIntent
from modules.parser.intents.resume_intent import ResumeIntent
from modules.parser.intents.status_intent import StatusIntent
from modules.parser.intents.remove_last_intent import RemoveLastIntent
from modules.parser.intents.clear_queue_intent import ClearQueueIntent
from modules.parser.intents.link_spotify_intent import LinkSpotifyIntent
from modules.parser.intents.disconnect_intent import DisconnectIntent
from modules.parser.intents.overlay_intent import OverlayIntent
from modules.parser.intents.help_intent import HelpIntent
from modules.parser.intents.queue_intent import QueueIntent
from modules.parser.intents.play_intent import PlayIntent

logger = logging.getLogger("rodolfo.parser")

INTENTS = [
    StopIntent(), PauseIntent(), SkipIntent(), ResumeIntent(),
    StatusIntent(), RemoveLastIntent(), ClearQueueIntent(),
    LinkSpotifyIntent(), DisconnectIntent(), OverlayIntent(),
    HelpIntent(), QueueIntent(), PlayIntent()
]

_SHUFFLE_RE = re.compile(
    r"\b(en\s+modo\s+)?(random|aleatorio|aleatoria|mezcla|mezclar|shuffle|al\s+azar)\b"
)

_ALIAS_ONLY_ACTIVATOR_RE = re.compile(r"(?<!\w)rodolfo(?!\w)")
_PRIMARY_ACTIVATOR_RE = re.compile(r"(?<!\w)oye\s+rodolfo(?!\w)")
_FALLBACK_MUSIC_HINTS = {
    "pon", "ponme", "pone", "poneme", "coloca", "colocame", "reproduce",
    "play", "escucha", "escuchemos", "encola", "agrega", "agregame",
    "playlist", "album", "disco", "musica", "cancion", "canciones",
    "tema", "temas",
}

@functools.lru_cache(maxsize=1024)
def _cached_parse_logic(raw_text: str, require_activator: bool) -> tuple:
    """Ejecuta la lógica de parseo pura y retorna (resultado_dict, list_candidatos) para cacheado."""
    if not raw_text:
        return {"action": "unknown"}, []

    # 1. Normalizar y corregir STT
    cmd_norm = normalize(raw_text)
    cmd_fixed = fix_common_stt_errors(cmd_norm)
    
    # 2. Activador
    has_activator, cmd_clean = strip_activator(cmd_fixed)
    alias_only_activator = (
        has_activator
        and bool(_ALIAS_ONLY_ACTIVATOR_RE.search(cmd_fixed))
        and not bool(_PRIMARY_ACTIVATOR_RE.search(cmd_fixed))
    )
    
    if require_activator and not has_activator:
        return {
            "action": "ignored", 
            "normalized_cmd": cmd_fixed,
            "activator_detected": False
        }, []

    # 3. Fillers
    cmd_clean = strip_fillers(cmd_clean)
    if not cmd_clean:
        return {
            "action": "greet",
            "normalized_cmd": cmd_fixed,
            "activator_detected": has_activator,
            "confidence": 1.0
        }, []

    # 4. Shuffle (modo random)
    shuffle = bool(_SHUFFLE_RE.search(cmd_clean))
    if shuffle:
        cmd_clean = _SHUFFLE_RE.sub("", cmd_clean).strip()

    # 5. Tokenizar
    ctx = tokenize(cmd_clean)
    
    # 6. Intent matching
    candidates = []
    for intent in INTENTS:
        try:
            match_res = intent.match(cmd_clean, ctx)
            if match_res:
                # Traspasar el shuffle si se detectó al inicio
                if not match_res.shuffle and shuffle:
                    match_res.shuffle = True
                candidates.append(match_res)
        except Exception as e:
            logger.error(f"[Parser] Error en intent {intent.name}: {e}")

    # 7. Resolución de conflictos por scoring
    if candidates:
        def get_priority(action):
            for i in INTENTS:
                if i.name == action or (action in ("hide_overlay", "show_overlay") and i.name == "overlay_control"):
                    return i.priority
            return 0
            
        candidates.sort(key=lambda r: (r.confidence, get_priority(r.action)), reverse=True)
        best = candidates[0]
        
        res = {
            "action": best.action,
            "confidence": round(best.confidence, 2),
            "normalized_cmd": cmd_clean,
            "activator_detected": has_activator,
        }
        if best.query:
            res["query"] = best.query
        if best.spotify_type:
            res["spotify_type"] = best.spotify_type
        if best.shuffle:
            res["shuffle"] = True
        return res, candidates

    # 8. Fallback Heurístico (reproducción genérica)
    if cmd_clean and len(cmd_clean) > 1:
        greetings = (
            "hola", "buenas", "alo", "oye", "hey", "rodolfo", "rodo",
            "ok", "okay", "dale", "listo", "bueno", "si", "sí", "aja",
            "ajá", "eh",
        )
        _reject_stop = {"callate", "callense", "calla", "cierra", "silenciate"}
        words_set = ctx.get("words_set", set())
        
        if words_set & _reject_stop:
            return {
                "action": "stop_music",
                "confidence": 0.8,
                "normalized_cmd": cmd_clean,
                "activator_detected": has_activator
            }, []
            
        if cmd_clean not in greetings:
            if len(words_set) == 1 and len(cmd_clean) < 4:
                return {
                    "action": "unknown",
                    "normalized_cmd": cmd_clean,
                    "activator_detected": has_activator
                }, []

            if alias_only_activator and not (words_set & _FALLBACK_MUSIC_HINTS):
                return {
                    "action": "unknown",
                    "normalized_cmd": cmd_clean,
                    "activator_detected": has_activator
                }, []
                
            q, stype = _detect_content_type(cmd_clean)
            res = {
                "action": "play_music",
                "query": q,
                "confidence": 0.6,
                "normalized_cmd": cmd_clean,
                "activator_detected": has_activator,
                "shuffle": shuffle
            }
            if stype:
                res["spotify_type"] = stype
            return res, []

    return {
        "action": "unknown",
        "normalized_cmd": cmd_clean,
        "activator_detected": has_activator
    }, []


def full_parse(raw_text: str, require_activator: bool = True) -> dict:
    """Punto de entrada unificado para el parser con telemetría y latencia."""
    start_time = time.perf_counter()
    
    # Delegar a la lógica de caché
    result, candidates = _cached_parse_logic(raw_text, require_activator)
    
    # Copiar el dict para no alterar la caché al añadir metadatos dinámicos
    result_copy = dict(result)
    
    latency = (time.perf_counter() - start_time) * 1000.0
    result_copy["parser_latency_ms"] = round(latency, 3)
    
    # Telemetría de baja confianza
    if result_copy.get("action") == "unknown":
        logger.warning(f"[TELEMETRIA:unknown_command] '{raw_text}' no se pudo interpretar")
    elif result_copy.get("confidence", 1.0) < 0.7 and result_copy.get("action") != "ignored":
        logger.info(f"[TELEMETRIA:low_confidence] '{raw_text}' -> {result_copy['action']} (confianza={result_copy.get('confidence')})")
        
    debug_msg = (
        f"[Parser] raw='{raw_text}' | normalized='{result_copy.get('normalized_cmd', '')}' | "
        f"selected={result_copy.get('action')} (conf={result_copy.get('confidence', 1.0)}) | "
        f"latency={result_copy['parser_latency_ms']}ms"
    )
    print(debug_msg)
    
    return result_copy
