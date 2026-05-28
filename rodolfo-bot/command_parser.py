"""
command_parser.py — Parser de comandos compartido entre
  voice_controller.py  (mic local del dueño)
  music_bot.py         (voice receive del canal de Discord)

Solo se parsean comandos relacionados con música. Los comandos del sistema
(volumen, cambiar dispositivo, salir) siguen viviendo en voice_controller.py
porque solo aplican a la PC del dueño.
"""

import re
import unicodedata

ACTIVATOR_NAMES = ("rodo",)


# ─── Normalización ─────────────────────────────────────────────────────────────
def normalize(cmd: str) -> str:
    """Lowercase, sin acentos, sin puntuación."""
    cmd = unicodedata.normalize("NFD", cmd)
    cmd = "".join(c for c in cmd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", "", cmd.lower().strip())


def strip_activator(cmd: str):
    """Returns (has_activator, cmd_sin_activador).
    Quita TODAS las ocurrencias del activador para manejar repeticiones del STT
    (ej: 'rodo rodo coloca X' → 'coloca X')."""
    names_re = "|".join(ACTIVATOR_NAMES)
    activator_re = re.compile(rf"\b(?:{names_re})\b[,\s]*")
    cleaned = activator_re.sub("", cmd).strip()
    if cleaned != cmd:
        return True, cleaned
    return False, cmd


def strip_fillers(cmd: str) -> str:
    """Elimina muletillas o palabras de relleno comunes al inicio de la frase."""
    while True:
        prev = cmd
        # Quita "y este", "este", "eh", "em", "a ver", "bueno", "pues", "o sea" al inicio
        cmd = re.sub(r"^(?:y\s+)?(?:este|eh|em|a\s+ver|bueno|pues|o\s+sea)\b[,\s]*", "", cmd)
        if cmd == prev:
            break
    return cmd



def fix_common_stt_errors(cmd: str) -> str:
    cmd = re.sub(r"\bpom\b",   "pon", cmd)
    cmd = re.sub(r"\bpong\b",  "pon", cmd)
    cmd = re.sub(r"\bbong\b",  "pon", cmd)
    cmd = re.sub(r"\bporn\b",  "pon", cmd)
    cmd = re.sub(r"\bpum\b",   "pon", cmd)
    cmd = re.sub(r"\bpomp[oó]n\b", "pon", cmd)
    cmd = re.sub(r"\bpompom\b", "pon", cmd)
    cmd = re.sub(r"\bpun\b",   "pon", cmd)
    cmd = re.sub(r"\bstock\b",   "stop", cmd)
    cmd = re.sub(r"\bdetente\b", "deten", cmd)  # "detente" → "deten" (stop)
    cmd = re.sub(r"\bskype\b",   "skip", cmd)
    # STT confunde el activador "rodo" con palabras similares
    cmd = re.sub(r"\bfrodo\b",   "rodo", cmd)
    cmd = re.sub(r"\brodolfo\b", "rodo", cmd)  # "Rodo" → STT → "Rodolfo"
    cmd = re.sub(r"\brod[oó]\b", "rodo", cmd)  # "rodó" con tilde
    # STT confunde "pon" con "para" cuando va seguido de contenido no musical
    # "para mi album X" → "pon mi album X"  (pero NO "para la música" que es stop)
    if not re.search(
        r"\bpara\s+(?:la\s+)?(?:musica|cancion|tema|reproduccion|esto|eso|todo)\b", cmd
    ):
        cmd = re.sub(r"\bpara\s+(mi|el|la|un|una|algo|musica\s+de)\b", r"pon \1", cmd)
    # "pon X en Spotify / de YouTube" → "pon X"
    # El usuario dice el servicio como indicación, no es parte del nombre de la canción
    cmd = re.sub(r"\s+(?:en|de)\s+(?:spotify|youtube|yt|deezer)\s*$", "", cmd)
    cmd = re.sub(
        r"\s+(?:en|a|por)\s+(?:mis\s+)?"
        r"(?:parlantes|altavoces|bocinas|mi\s+pc|la\s+pc|local)\s*$",
        "",
        cmd,
    )
    cmd = re.sub(r"\s+(?:aqui|aca)\s*$", "", cmd)
    return cmd


# ─── Parser de música ──────────────────────────────────────────────────────────
def parse_music(cmd: str):
    """Devuelve dict con action o None si no es un comando de música."""
    if not cmd or len(cmd) < 2:
        return None

    # STOP / PAUSE / SKIP rápidos
    if (re.search(r"\b(stop|deten|detener|detenga|detiene|para|parar|pare|paren)\b.*\b(musica|cancion|tema|todo|esto|esta|reproduccion)\b", cmd) or
        cmd in ("stop", "para", "deten", "detener", "detenga", "alto", "basta", "pare", "paren") or
        re.match(r"^stop[\s\W]*$", cmd) or        # "stop stop", "stop!", etc.
        re.match(r"^(para|deten|alto)[\s\W]*$", cmd)):
        return {"action": "stop_music"}
    if re.search(r"\b(pausa|pausala)\b", cmd):
        return {"action": "pause_music"}
    if re.search(r"\b(salta|saltala|pasala|pasalo|siguiente|skip|salte)\b", cmd):
        return {"action": "skip_music"}

    # "Cállate" y expresiones de silencio → detener música
    if re.search(r"\b(callate|callense|calla|cierra|silenciate)\b", cmd):
        return {"action": "stop_music"}


    # Resume — "play" solo sin canción, o palabras de reanudar
    _resume_words = {
        "sigue", "continua", "reanuda", "resume",
        "dale play", "vuelve a poner",
        "reanuda musica", "reanuda la musica",
        "continua musica", "continua la musica",
        "sigue la musica", "sigue con la musica",
    }
    if cmd in _resume_words or any(w in cmd for w in _resume_words):
        return {"action": "resume_music"}
    if cmd == "play":   # "rodo play" solo = reanudar
        return {"action": "resume_music"}

    # Estado
    if any(w in cmd for w in [
        "que esta sonando", "que cancion es", "que suena",
        "como se llama esta", "que tema es", "que estoy escuchando",
        "cancion actual",
    ]):
        return {"action": "music_status"}

    # Eliminar SOLO la última de la cola
    if re.search(
        r"\b(elimina|eliminar|borra|borrar|quita|quitar|saca|sacar|"
        r"elimino|elimine|borro|quito|saco)\s+"
        r"(?:la\s+)?ultima\b", cmd):
        return {"action": "remove_last"}
    if any(w in cmd for w in [
        "quita esa cancion", "quita esa", "saca esa cancion",
        "borra esa cancion", "elimina esa cancion",
        "elimina la cancion que acabo", "saca la ultima",
    ]):
        return {"action": "remove_last"}

    # Limpiar cola completa — regex flexible (elimina/borra/quita + toda/todas + cola/lista/canciones)
    if re.search(
        r"\b(?:elimina(?:r)?|borra(?:r)?|quita(?:r)?|vacia(?:r)?|limpia(?:r)?)\s+"
        r"(?:tod[ao]s?\s+)?(?:la\s+|las\s+|el\s+)?(?:cola|lista|canciones|temas)\b", cmd
    ):
        return {"action": "clear_queue"}

    # Limpiar cola completa — palabras exactas
    if any(w in cmd for w in [
        "limpia la cola", "limpiar cola", "limpia cola",
        "limpia la lista", "limpiar lista", "limpia lista",
        "vacia la cola", "vaciar cola", "vacia cola",
        "vacia la lista", "vaciar lista", "vacia lista",
        "borra la cola", "borrar cola", "borra cola",
        "borra la lista", "borrar lista", "borra lista",
        "quita la cola", "quitar la cola",
        "quita la lista", "quitar la lista",
        "quita todo de la cola", "quita todas las canciones de la cola",
        "quita las canciones de la cola",
        "elimina la cola", "eliminar cola", "elimina cola",
        "elimina la lista", "eliminar lista", "elimina lista",
        "elimino la lista", "eligio la lista",
        "eliminan la lista", "eliminan la cola", "eliminan",
    ]):
        return {"action": "clear_queue"}

    # Biblioteca personal de Spotify — "mis guardadas", "mis me gusta", etc.
    if re.search(
        r"\b(?:mis|mi)\s+"
        r"(?:guardadas?|me\s+gusta|favoritas?|likes?|canciones?\s+guardadas?|"
        r"musicas?\s+guardadas?|temas?\s+guardados?)\b",
        cmd,
    ):
        shuffle_in_cmd = bool(_SHUFFLE_RE.search(cmd))
        return {"action": "play_music", "query": "", "spotify_type": "saved_tracks",
                "shuffle": shuffle_in_cmd}

    # Vincular Spotify: "vincula mi spotify", "conecta mi spotify", etc.
    if re.search(
        r"\b(?:vincula(?:me)?|conecta(?:me)?|link|enlaza(?:me)?)\b.{0,20}\bspotify\b",
        cmd,
    ):
        return {"action": "link_spotify"}

    # Disconnect del canal de voz
    if any(w in cmd for w in [
        "sal del canal", "sal de la voz", "vete del canal",
        "desconectate", "desconecta bot",
        "salte de discord", "salte del discord", "sal de discord",
        "hasta luego", "chau", "chao", "adios", "nos vemos",
        "cierra discord", "sal ya",
    ]):
        return {"action": "disconnect_music"}

    # Ocultar overlay (se maneja localmente en Rodo.exe, no va al bot)
    if any(w in cmd for w in [
        "ocultate", "oculta", "escondete", "esconde",
        "sal de mi pantalla", "sal de la pantalla", "quitate de la pantalla",
        "quitate", "desaparece", "vete de la pantalla",
        "no te veo", "escondete de mi pantalla",
    ]):
        return {"action": "hide_overlay"}

    # Mostrar overlay
    if any(w in cmd for w in [
        "muestrate", "muestra", "aparece", "donde estas",
        "donde te fuiste", "vuelve a aparecer", "aparece en pantalla",
        "sal", "asomarte", "asomarte",
    ]):
        return {"action": "show_overlay"}

    # Ayuda / Comandos
    if any(w in cmd for w in [
        "ayuda", "help", "comandos", "que sabes hacer", "que puedes hacer",
        "como te uso", "que haces", "dime tus comandos", "dime los comandos",
    ]):
        return {"action": "help"}

    # Cola explícita: "luego pon X"
    qm = re.match(
        r"^(?:luego|despues|posteriormente|enseguida|al\s+rato|cuando\s+(?:termine|acabe))\s+"
        r"(?:pon(?:me)?|coloca(?:me)?|echa(?:me)?|metele|reproduce(?:me)?|tira(?:me)?)\s+"
        r"(.+?)$", cmd)
    if qm:
        rest = qm.group(1).strip()
        rest = re.sub(r"^(?:la|el|un|una|los|las)\s+", "", rest)
        rest = re.sub(r"^(?:musica|cancion|tema|rola|track)\s*(?:de\s+)?", "", rest)
        if rest and len(rest) > 1:
            return {"action": "queue_music", "query": rest}

    # "encola X" / "agrega X"
    qm2 = re.match(r"^(?:encola(?:me)?|agrega(?:me)?|agregar|mete(?:me)?|meter)\s+(.+?)$", cmd)
    if qm2:
        rest = qm2.group(1).strip()
        rest = re.sub(r"\s+(?:a\s+la\s+cola|en\s+la\s+cola|en\s+cola)$", "", rest)
        rest = re.sub(r"^(?:la|el|un|una|los|las)\s+", "", rest)
        rest = re.sub(r"^(?:musica|cancion|tema|rola)\s*(?:de\s+)?", "", rest)
        if rest and len(rest) > 1:
            return {"action": "queue_music", "query": rest}

    # Comandos de transferencia a PC local — los maneja amigo.py, no el bot.
    # Si llegan aquí por error, los ignoramos para que no se traten como canciones.
    _xfer_verbs = {"pasemos", "pasa", "pasalo", "pasala", "pasame",
                   "vamos", "vamonos", "mueve", "manda", "mandame",
                   "cambia", "trae"}
    _xfer_dest  = ["mi pc", "a la pc", "al pc", "a local", "al local",
                   "mis parlantes", "mis altavoces", " aqui", " aca"]
    if bool(set(cmd.split()) & _xfer_verbs) and any(d in cmd for d in _xfer_dest):
        return {"action": "ignored"}

    # Verbos de poner música
    play_verbs = [
        "ponme", "pon", "pone", "poner", "ponle", "ponele",
        "reproduce", "reproduceme", "reproducir", "play",
        "coloca", "colocame", "colocar",
        "echa", "echame", "tira", "tirame",
        "pongamos", "escuchemos",
        "quiero escuchar", "quiero oir", "quisiera escuchar",
        "metele", "dame", "con",
    ]
    for verb in play_verbs:
        if cmd == verb or cmd.startswith(verb + " "):
            rest = cmd[len(verb):].strip()
            rest = re.sub(r"^(?:me\s+)?", "", rest)
            # Detectar tipo de contenido ANTES de limpiar prefijos indicadores
            rest, spotify_type = _detect_content_type(rest)
            if not spotify_type:
                # Sin tipo → limpiar prefijos genéricos (artículos, palabras de relleno)
                rest = re.sub(r"^(?:la|el|un|una|los|las)\s+", "", rest)
                rest = re.sub(r"^(?:musica|cancion|tema|rola|track|tonada)\s*(?:de\s+)?", "", rest)
                rest = re.sub(r"^(?:de\s+)", "", rest)
            rest = re.sub(r"\s*(?:por\s+favor|porfa|porfis)\s*$", "", rest)
            if re.search(r"\s+a\s+la\s+cola$", rest):
                rest = re.sub(r"\s+a\s+la\s+cola$", "", rest).strip()
                if rest and len(rest) > 1:
                    res = {"action": "queue_music", "query": rest}
                    if spotify_type:
                        res["spotify_type"] = spotify_type
                    return res
            rest = rest.strip()
            if rest and len(rest) > 1 and rest not in ("musica", "cancion", "tema", "algo", "rola"):
                res = {"action": "play_music", "query": rest}
                if spotify_type:
                    res["spotify_type"] = spotify_type
                return res
            return {"action": "play_music"}

    # Verbo de música embebido en el medio del comando (STT agrega ruido al inicio)
    # Ej: "un condenado pon el millon de paulo londra" → extrae "pon el millon de paulo londra"
    # Ej: "no reproduce flaca de andres calamaro"     → extrae "reproduce flaca de andres calamaro"
    _embedded = re.search(
        r"\b(ponme|pon|pone|reproduce(?:me)?|coloca(?:me)?)\b\s+(.+)",
        cmd,
    )
    if _embedded:
        sub_cmd = f"{_embedded.group(1)} {_embedded.group(2).strip()}"
        result = parse_music(sub_cmd)
        if result and result.get("action") in ("play_music", "queue_music") and result.get("query"):
            return result

    return None


# ─── Punto de entrada unificado ────────────────────────────────────────────────
_SHUFFLE_RE = re.compile(
    r"\b(en\s+modo\s+)?(random|aleatorio|aleatoria|mezcla|mezclar|shuffle|al\s+azar)\b"
)

# ─── Detección de tipo de contenido ──────────────────────────────────────────
# El texto ya está normalizado (sin acentos, lowercase) cuando llega aquí.
_CONTENT_PATTERNS = [
    # Artista: "algo de X", "música de X", "canciones de X", "lo de X"
    (re.compile(
        r"^(?:algo|musica|canciones?|temas?|lo|un\s+poco)\s+de\s+(.+)$"
    ), "artist"),
    # Álbum: "[mi/el/la/un] album/disco/lp [de] X"
    (re.compile(
        r"^(?:(?:mi|el|la|un)\s+)?(?:album|disco|lp)\s+(?:de\s+)?(.+)$"
    ), "album"),
    # Playlist: "[mi/la/el/una] playlist/lista [de] X"
    (re.compile(
        r"^(?:(?:mi|la|el|una?)\s+)?(?:playlist|lista(?:\s+de\s+reproduccion)?)\s+(?:de\s+)?(.+)$"
    ), "playlist"),
]


def _detect_content_type(text: str) -> tuple[str, str | None]:
    """
    Detecta si el texto describe un tipo de contenido específico.
    Retorna (query_limpia, spotify_type) donde spotify_type puede ser
    "album", "playlist", "artist" o None (canción / búsqueda libre).

    Ejemplos (texto ya normalizado):
      "algo de bad bunny"          → ("bad bunny",   "artist")
      "album 360"                  → ("360",          "album")
      "mi playlist de trap"        → ("trap",         "playlist")
      "el disco de soda stereo"    → ("soda stereo",  "album")
      "despacito"                  → ("despacito",    None)
    """
    for pattern, ctype in _CONTENT_PATTERNS:
        m = pattern.match(text.strip())
        if m:
            return m.group(1).strip(), ctype
    return text, None


def full_parse(raw_text: str, require_activator: bool = True):
    """Parser completo: normaliza → corrige STT → quita activador → parsea."""
    if not raw_text:
        return {"action": "unknown"}

    cmd = normalize(raw_text)
    cmd = fix_common_stt_errors(cmd)   # antes de strip_activator: "rodolfo" → "rodo"
    has_activator, cmd = strip_activator(cmd)

    if require_activator and not has_activator:
        return {"action": "ignored"}

    cmd = strip_fillers(cmd)

    if not cmd:
        return {"action": "greet"}

    # Detectar modo random y limpiarlo del comando antes de parsear
    shuffle = bool(_SHUFFLE_RE.search(cmd))
    if shuffle:
        cmd = _SHUFFLE_RE.sub("", cmd).strip()

    parsed = parse_music(cmd)
    if parsed and parsed.get("action") in ("play_music", "queue_music"):
        parsed["shuffle"] = shuffle
        return parsed
    if parsed:
        return parsed

    # Fallback: si tiene activador y no es comando conocido, intentar como play_music
    # SOLO si no contiene palabras de rechazo/insulto
    if cmd and len(cmd) > 1:
        greetings = ("hola", "buenas", "alo", "oye", "hey", "rodolfo", "rodo")
        _reject_stop = {"callate", "callense", "calla", "cierra", "silenciate"}
        words_set = set(cmd.split())
        if words_set & _reject_stop:
            return {"action": "stop_music"}
        if cmd not in greetings:
            # Descartar queries demasiado cortas (palabras sueltas < 4 chars = basura del STT)
            if len(words_set) == 1 and len(cmd) < 4:
                return {"action": "unknown"}
            q, stype = _detect_content_type(cmd)
            res = {"action": "play_music", "query": q, "shuffle": shuffle}
            if stype:
                res["spotify_type"] = stype
            return res

    return {"action": "unknown", "cmd": cmd}
