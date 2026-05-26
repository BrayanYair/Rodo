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

ACTIVATOR_NAMES = ("rodolfo", "jarvis", "asistente", "bot")


# ─── Normalización ─────────────────────────────────────────────────────────────
def normalize(cmd: str) -> str:
    """Lowercase, sin acentos, sin puntuación."""
    cmd = unicodedata.normalize("NFD", cmd)
    cmd = "".join(c for c in cmd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", "", cmd.lower().strip())


def strip_activator(cmd: str):
    """Returns (has_activator, cmd_sin_activador).
    Acepta el activador al inicio, en medio o al final de la frase."""
    names_re = "|".join(ACTIVATOR_NAMES)
    activator_re = re.compile(rf"\b(?:{names_re})\b[,\s]*")
    m = activator_re.search(cmd)
    if m:
        after  = cmd[m.end():].strip()
        before = cmd[:m.start()].strip()
        # Preferimos lo que viene DESPUÉS ("rodolfo X")
        # pero si nada hay, usamos lo de ANTES ("X rodolfo")
        if after:
            return True, after
        if before:
            return True, before
        return True, ""
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
    cmd = re.sub(r"\bstock\b", "stop", cmd)
    cmd = re.sub(r"\bskype\b", "skip", cmd)
    return cmd


# ─── Parser de música ──────────────────────────────────────────────────────────
def parse_music(cmd: str):
    """Devuelve dict con action o None si no es un comando de música."""
    if not cmd or len(cmd) < 2:
        return None

    # STOP / PAUSE / SKIP rápidos
    if (re.search(r"\b(stop|deten|detener|detenga|detiene|para|parar|pare|paren)\b.*\b(musica|cancion|tema|todo|esto|esta|reproduccion)\b", cmd) or
        cmd in ("stop", "para", "deten", "detener", "detenga", "alto", "basta", "pare", "paren")):
        return {"action": "stop_music"}
    if re.search(r"\b(pausa|pausala)\b", cmd):
        return {"action": "pause_music"}
    if re.search(r"\b(salta|saltala|pasala|pasalo|siguiente|skip|salte)\b", cmd):
        return {"action": "skip_music"}

    # "Cállate" y expresiones de silencio → detener música
    if re.search(r"\b(callate|callense|calla|cierra|silenciate)\b", cmd):
        return {"action": "stop_music"}

    # Insultos sin intención de comando → descartar (no buscar canción)
    if re.search(r"\b(idiota|bobo|estupido|estupida|imbecil|mierda|pendejo|guevon|marico|maldito|maldita|bruto)\b", cmd):
        return {"action": "unknown"}

    # Resume
    if any(w in cmd for w in [
        "reanuda musica", "reanuda la musica", "continua musica",
        "continua la musica", "sigue la musica", "sigue con la musica",
        "resume", "dale play", "vuelve a poner",
    ]):
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
            rest = re.sub(r"^(?:la|el|un|una|los|las|algo\s+de)\s+", "", rest)
            rest = re.sub(r"^(?:musica|cancion|tema|rola|track|tonada)\s*(?:de\s+)?", "", rest)
            rest = re.sub(r"^(?:de\s+)", "", rest)
            rest = re.sub(r"\s*(?:por\s+favor|porfa|porfis)\s*$", "", rest)
            if re.search(r"\s+a\s+la\s+cola$", rest):
                rest = re.sub(r"\s+a\s+la\s+cola$", "", rest).strip()
                if rest and len(rest) > 1:
                    return {"action": "queue_music", "query": rest}
            rest = rest.strip()
            if rest and len(rest) > 1 and rest not in ("musica", "cancion", "tema", "algo", "rola"):
                return {"action": "play_music", "query": rest}
            return {"action": "play_music"}

    return None


# ─── Punto de entrada unificado ────────────────────────────────────────────────
def full_parse(raw_text: str, require_activator: bool = True):
    """Parser completo: normaliza → quita activador → corrige → parsea."""
    if not raw_text:
        return {"action": "unknown"}

    cmd = normalize(raw_text)
    has_activator, cmd = strip_activator(cmd)

    if require_activator and not has_activator:
        return {"action": "ignored"}

    cmd = strip_fillers(cmd)

    if not cmd:
        return {"action": "greet"}

    cmd = fix_common_stt_errors(cmd)

    parsed = parse_music(cmd)
    if parsed:
        return parsed

    # Fallback: si tiene activador y no es comando conocido, intentar como play_music
    # SOLO si no contiene palabras de rechazo/insulto
    if cmd and len(cmd) > 1:
        greetings = ("hola", "buenas", "alo", "oye", "hey", "rodolfo")
        _reject_stop   = {"callate", "callense", "calla", "cierra", "silenciate"}
        _reject_ignore = {
            "maldito", "maldita", "idiota", "bruto", "bobo",
            "pendejo", "mierda", "guevon", "marico", "imbecil",
            "estupido", "estupida",
        }
        words_set = set(cmd.split())
        if words_set & _reject_stop:
            return {"action": "stop_music"}
        if cmd not in greetings and not (words_set & _reject_ignore):
            # Descartar queries demasiado cortas (palabras sueltas < 4 chars = basura del STT)
            if len(words_set) == 1 and len(cmd) < 4:
                return {"action": "unknown"}
            return {"action": "play_music", "query": cmd}

    return {"action": "unknown", "cmd": cmd}
