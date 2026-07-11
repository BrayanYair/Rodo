import re
import unicodedata
import functools

BRAND_NAME = "Byarox"
ASSISTANT_NAME = "Rodolfo"
PRIMARY_ACTIVATOR = "oye rodo"
ACTIVATOR_NAMES = (PRIMARY_ACTIVATOR, "rodo", "oye rodolfo", "rodolfo")

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

# Géneros musicales — "pon reggaeton" busca una playlist del género en vez de
# un único track, así la cola queda con varias canciones y sigue sonando.
_GENRES = {
    "reggaeton", "regueton", "salsa", "bachata", "cumbia", "cumbias",
    "vallenato", "merengue", "rock", "rock en español", "pop",
    "pop en español", "trap", "urbano", "musica urbana", "electronica",
    "reggae", "banda", "ranchera", "corridos", "bolero", "jazz", "blues",
    "rap", "hip hop", "edm", "techno", "house", "criolla",
    "musica criolla", "huayno", "baladas", "balada", "disco", "funk",
    "soul", "kpop", "k pop", "indie", "punk", "metal", "dembow", "perreo",
}
_GENRE_PREFIX_RE = re.compile(r"^(?:(?:algo|musica|canciones?|temas?|un\s+poco)\s+de|un|una)\s+(.+)$")

def _detect_content_type(text: str) -> tuple[str, str | None]:
    """
    Detecta si el texto describe un tipo de contenido específico.
    Retorna (query_limpia, spotify_type).
    """
    t = text.strip()

    m = _GENRE_PREFIX_RE.match(t)
    genre_candidate = m.group(1).strip() if m else t
    if genre_candidate in _GENRES:
        return genre_candidate, "playlist"

    for pattern, ctype in _CONTENT_PATTERNS:
        m = pattern.match(t)
        if m:
            return m.group(1).strip(), ctype
    return text, None
