"""
responses.py — Frases naturales para Rodolfo.

En vez de respuestas robóticas idénticas siempre, Rodolfo elige al azar
entre variantes casuales — como un amigo que te ayuda con la música.

Uso:
    from responses import music_started
    text = music_started("Despacito - Luis Fonsi")
    # → "Va Despacito - Luis Fonsi"  o  "Ahí está, Despacito - Luis Fonsi"  etc.
"""

import random


def _pick(options):
    return random.choice(options)


def _trim(text, max_len=60):
    """Acorta sin cortar palabras a la mitad."""
    if not text or len(text) <= max_len:
        return text
    cut = text[:max_len]
    # Cortar en el último espacio (no en medio de palabra)
    last_space = cut.rfind(" ")
    if last_space > max_len * 0.6:
        cut = cut[:last_space]
    # Quitar comillas/puntos sueltos al final
    return cut.rstrip(" .,;:()[]\"'")


# ─── Saludos ──────────────────────────────────────────────────────────────────
def greet_initial():
    return _pick([
        "Hola, aquí Rodolfo.",
        "Qué tal, listo para lo que sea.",
        "Aquí ando, dime qué quieres.",
        "Dale, soy todo oídos.",
        "Listo, ¿qué hacemos?",
    ])


def greet_reply():
    """Cuando alguien solo dice 'Rodolfo' sin comando."""
    return _pick([
        "Dime.",
        "¿Qué pasó?",
        "Aquí ando.",
        "Te escucho.",
        "Mande.",
        "Dale, dispara.",
    ])


# ─── Música: arrancando una canción ──────────────────────────────────────────
def music_started(title):
    title = _trim(title)
    return _pick([
        f"Va {title}.",
        f"Ahí está, {title}.",
        f"Suena {title}.",
        f"Dale, {title}.",
        f"Sonando, {title}.",
        f"Aquí va, {title}.",
    ])


def music_queued(title, position=None):
    title = _trim(title)
    if position and position > 1:
        return _pick([
            f"{title}, en cola, posición {position}.",
            f"Te lo dejo de número {position}.",
            f"Anotado, {title} en {position}.",
            f"{title}, lugar {position}.",
        ])
    return _pick([
        f"Va en cola, {title}.",
        f"Te lo agrego, {title}.",
        f"Anotado, {title}.",
        f"{title}, en cola.",
        f"Le sigue {title}.",
    ])


def music_started_short():
    """Confirmación ultra-corta — minimiza la interrupción de la música."""
    return _pick(["Va.", "Dale.", "Listo.", "Suena.", "Ahí va."])


def music_queued_short():
    """Confirmación ultra-corta de encolar — minimiza la interrupción."""
    return _pick(["En cola.", "Anotado.", "Listo.", "Puesto."])


def music_multiple_queued(count, first_title=None):
    if first_title:
        first_title = _trim(first_title, 50)
        return _pick([
            f"Le meto {count} canciones, empezando con {first_title}.",
            f"Va, {count} canciones, primera: {first_title}.",
            f"{count} agregadas, empezamos con {first_title}.",
        ])
    return _pick([
        f"Listo, {count} canciones agregadas.",
        f"Va, {count} a la cola.",
        f"Te metí {count} canciones.",
        f"{count} canciones más en cola.",
    ])


# ─── Música: skip / next ──────────────────────────────────────────────────────
def music_skipped():
    return _pick([
        "Siguiente.",
        "Próxima.",
        "Va la que sigue.",
        "Cambio.",
        "Ahí va otra.",
        "Saltada.",
    ])


# ─── Música: stop ─────────────────────────────────────────────────────────────
def music_stopped():
    return _pick([
        "Listo, paré.",
        "Ya está, apagado.",
        "Música off.",
        "Cortada.",
        "Hasta ahí.",
    ])


# ─── Música: pause ────────────────────────────────────────────────────────────
def music_paused():
    return _pick([
        "Pauso.",
        "Pausa.",
        "Espera.",
        "Freno ahí.",
    ])


# ─── Música: resume ───────────────────────────────────────────────────────────
def music_resumed():
    return _pick([
        "Dale.",
        "Seguimos.",
        "Sigo.",
        "Ahí va de nuevo.",
    ])


# ─── Música: estado actual ────────────────────────────────────────────────────
def music_status(title):
    title = _trim(title)
    return _pick([
        f"Está sonando {title}.",
        f"Ahora suena {title}.",
        f"Va {title}.",
        f"{title}, en este momento.",
    ])


# ─── Música: track eliminado de la cola ───────────────────────────────────────
def queue_last_removed(title=None):
    if title:
        title = _trim(title, 40)
        return _pick([
            f"Listo, saqué {title}.",
            f"Eliminé {title} de la cola.",
            f"Quité {title}.",
        ])
    return _pick([
        "Listo, saqué la última.",
        "Quité la última canción.",
        "Eliminada.",
    ])


def queue_empty_remove():
    return _pick([
        "La cola está vacía.",
        "No hay nada en cola para quitar.",
        "Cola vacía.",
    ])


def music_status_nothing():
    return _pick([
        "Nada por ahora.",
        "Silencio total.",
        "No hay música.",
        "Sin música.",
    ])


# ─── Música: cola limpia ──────────────────────────────────────────────────────
def queue_cleared(n):
    if n == 0:
        return _pick([
            "La cola estaba vacía.",
            "Nada en cola.",
            "Ya estaba vacía.",
        ])
    return _pick([
        f"Listo, saqué {n} canciones.",
        f"Cola limpia, {n} fuera.",
        f"Borré {n} de la cola.",
        f"Ya, {n} eliminadas.",
    ])


# ─── Música: desconexión del bot ──────────────────────────────────────────────
def disconnected():
    return _pick([
        "Listo, me salgo.",
        "Me retiro.",
        "Hasta luego, salgo del canal.",
        "Me voy del canal.",
    ])


# ─── Volumen ──────────────────────────────────────────────────────────────────
def volume_up():
    return _pick([
        "Subí el volumen.",
        "Más fuerte.",
        "Subido.",
        "Más alto.",
    ])


def volume_down():
    return _pick([
        "Bajé el volumen.",
        "Más bajo.",
        "Bajado.",
        "Más suavecito.",
    ])


def volume_mute():
    return _pick([
        "Silencio.",
        "Muteado.",
        "Cero.",
    ])


def volume_set(level):
    return _pick([
        f"Volumen al {level}.",
        f"{level} por ciento.",
        f"Ahí, en {level}.",
    ])


# ─── Errores y avisos ─────────────────────────────────────────────────────────
def error_no_voice_channel():
    return _pick([
        "No estás en un canal de voz, únete primero.",
        "Métete a un canal de voz primero.",
        "Necesito que te conectes a un canal de voz.",
    ])


def error_not_found():
    return _pick([
        "No encontré esa canción.",
        "Nada con ese nombre.",
        "No la pude encontrar.",
    ])


def error_generic():
    return _pick([
        "Algo salió mal.",
        "No pude hacerlo.",
        "Hubo un problema.",
        "Algo falló.",
    ])


def error_bot_offline():
    return _pick([
        "El bot no está corriendo, ¿lo iniciaste?",
        "No tengo conexión con el bot.",
        "El bot está dormido.",
    ])


def error_unknown():
    return _pick([
        "No entendí, ¿puedes repetir?",
        "No te capté.",
        "¿Cómo dices?",
        "No estoy seguro de qué quieres.",
    ])


def error_no_query():
    return _pick([
        "¿Qué canción quieres?",
        "Dime qué poner.",
        "¿Qué pongo?",
    ])


def error_pause_nothing():
    return _pick([
        "No hay música.",
        "Nada que pausar.",
        "Silencio ya.",
    ])


def error_resume_nothing():
    return _pick([
        "No hay nada pausado.",
        "Nada que reanudar.",
    ])


# ─── Despedidas ───────────────────────────────────────────────────────────────
def goodbye():
    return _pick([
        "Hasta luego.",
        "Nos vemos.",
        "Chao.",
        "Adiós.",
        "Hablamos.",
    ])
