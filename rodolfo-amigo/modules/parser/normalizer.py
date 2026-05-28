import re
import unicodedata
import functools

ACTIVATOR_NAMES = ("byarox",)

@functools.lru_cache(maxsize=1024)
def normalize(cmd: str) -> str:
    """Lowercase, sin acentos, sin puntuación."""
    cmd = unicodedata.normalize("NFD", cmd)
    cmd = "".join(c for c in cmd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", "", cmd.lower().strip())

def tokenize(cmd: str) -> dict:
    """Retorna tokens y bigramas del comando."""
    words = cmd.split()
    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words)-1)]
    return {
        "words": words,
        "bigrams": bigrams,
        "words_set": set(words),
        "raw_cmd": cmd
    }

def strip_fillers(cmd: str) -> str:
    """Elimina muletillas o palabras de relleno comunes al inicio de la frase."""
    while True:
        prev = cmd
        # Quita "y este", "este", "eh", "em", "a ver", "bueno", "pues", "o sea" al inicio
        cmd = re.sub(r"^(?:y\s+)?(?:este|eh|em|a\s+ver|bueno|pues|o\s+sea)\b[,\s]*", "", cmd)
        if cmd == prev:
            break
    return cmd

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
    Retorna (query_limpia, spotify_type).
    """
    for pattern, ctype in _CONTENT_PATTERNS:
        m = pattern.match(text.strip())
        if m:
            return m.group(1).strip(), ctype
    return text, None
