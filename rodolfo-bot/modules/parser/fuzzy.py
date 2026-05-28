import re
from modules.parser.normalizer import ACTIVATOR_NAMES

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

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
    Verifica si el inicio del comando contiene una palabra similar al activador 'rodo'.
    Retorna (has_activator, cleaned_cmd).
    """
    # 1. Comprobar coincidencia exacta primero
    for name in ACTIVATOR_NAMES:
        # Coincidencia exacta al inicio
        if cmd.startswith(f"{name} ") or cmd == name:
            cleaned = cmd[len(name):].strip()
            return True, cleaned
        # Coincidencia en cualquier parte del comando (ej: "pon rodo flaca")
        if f" {name} " in f" {cmd} ":
            cleaned = re.sub(rf"\b{name}\b[,\s]*", "", cmd).strip()
            return True, cleaned

    # 2. Si no hay coincidencia exacta, usar RapidFuzz en la primera palabra
    words = cmd.split()
    if not words:
        return False, cmd

    first_word = words[0]
    for name in ACTIVATOR_NAMES:
        ratio = fuzzy_match_ratio(first_word, name)
        if ratio >= threshold:
            cleaned = " ".join(words[1:]).strip()
            return True, cleaned

    return False, cmd

def strip_activator(cmd: str) -> tuple[bool, str]:
    """
    Intenta remover el activador (exacto o difuso).
    Retorna (has_activator, cmd_limpio).
    """
    # Intentar remoción exacta por regex múltiple
    names_re = "|".join(ACTIVATOR_NAMES)
    activator_re = re.compile(rf"\b(?:{names_re})\b[,\s]*")
    cleaned = activator_re.sub("", cmd).strip()
    if cleaned != cmd:
        return True, cleaned

    # Fallback a remoción difusa
    return check_fuzzy_activator(cmd)
