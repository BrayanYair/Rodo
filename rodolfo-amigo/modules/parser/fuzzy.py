import re
from modules.parser.normalizer import ACTIVATOR_NAMES

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False


def _activators() -> tuple[str, ...]:
    return tuple(sorted(ACTIVATOR_NAMES, key=len, reverse=True))


def fuzzy_match_ratio(s1: str, s2: str) -> float:
    """Retorna un score entre 0.0 y 1.0 indicando similitud de cadena."""
    if not RAPIDFUZZ_AVAILABLE:
        return 1.0 if s1 == s2 else 0.0
    return fuzz.ratio(s1, s2) / 100.0


def fuzzy_match_partial(s1: str, s2: str) -> float:
    """Retorna similitud parcial."""
    if not RAPIDFUZZ_AVAILABLE:
        return 1.0 if s1 in s2 or s2 in s1 else 0.0
    return fuzz.partial_ratio(s1, s2) / 100.0


def check_fuzzy_activator(cmd: str, threshold: float = 0.8) -> tuple[bool, str]:
    """
    Verifica si el comando contiene una frase similar al activador.
    Retorna (has_activator, cleaned_cmd).
    """
    for name in _activators():
        if cmd.startswith(f"{name} ") or cmd == name:
            return True, cmd[len(name):].strip()

        if f" {name} " in f" {cmd} ":
            cleaned = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)[,\s]*", "", cmd).strip()
            return True, cleaned

    words = cmd.split()
    if not words:
        return False, cmd

    for name in _activators():
        n_words = len(name.split())
        candidate = " ".join(words[:n_words])
        ratio = fuzzy_match_ratio(candidate, name)
        if ratio >= threshold:
            return True, " ".join(words[n_words:]).strip()

    return False, cmd


def strip_activator(cmd: str) -> tuple[bool, str]:
    """
    Intenta remover el activador (exacto o difuso).
    Retorna (has_activator, cmd_limpio).
    """
    names_re = "|".join(re.escape(name) for name in _activators())
    activator_re = re.compile(rf"(?<!\w)(?:{names_re})(?!\w)[,\s]*")
    cleaned = activator_re.sub("", cmd).strip()
    if cleaned != cmd:
        return True, cleaned

    return check_fuzzy_activator(cmd)
