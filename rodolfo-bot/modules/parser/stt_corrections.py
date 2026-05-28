import re

def fix_common_stt_errors(cmd: str) -> str:
    """Corrige errores frecuentes de reconocimiento de voz (ASR corruption)."""
    cmd = re.sub(r"\bpom\b",   "pon", cmd)
    cmd = re.sub(r"\bpong\b",  "pon", cmd)
    cmd = re.sub(r"\bbong\b",  "pon", cmd)
    cmd = re.sub(r"\bporn\b",  "pon", cmd)
    cmd = re.sub(r"\bpum\b",   "pon", cmd)
    cmd = re.sub(r"\bpomp[oó]n\b", "pon", cmd)
    cmd = re.sub(r"\bpompom\b", "pon", cmd)
    cmd = re.sub(r"\bpun\b",   "pon", cmd)
    cmd = re.sub(r"\bstock\b",   "stop", cmd)
    cmd = re.sub(r"\bdetente\b", "deten", cmd)  # "detente" -> "deten" (stop)
    cmd = re.sub(r"\bskype\b",   "skip", cmd)
    
    # Activadores deformados comunes — variantes de "byarox" que Google STT genera
    cmd = re.sub(r"\bbiarox\b",  "byarox", cmd)
    cmd = re.sub(r"\bbiharox\b", "byarox", cmd)
    cmd = re.sub(r"\byarox\b",   "byarox", cmd)
    cmd = re.sub(r"\bbyaro\b",   "byarox", cmd)

    # Corregir "para" por "pon" cuando no es una orden de parada
    if not re.search(
        r"\bpara\s+(?:la\s+)?(?:musica|cancion|tema|reproduccion|esto|eso|todo)\b", cmd
    ):
        cmd = re.sub(r"\bpara\s+(mi|el|la|un|una|algo|musica\s+de)\b", r"pon \1", cmd)
        
    # Limpieza de sufijos redundantes
    cmd = re.sub(r"\s+(?:en|de)\s+(?:spotify|youtube|yt|deezer)\s*$", "", cmd)
    cmd = re.sub(
        r"\s+(?:en|a|por)\s+(?:mis\s+)?"
        r"(?:parlantes|altavoces|bocinas|mi\s+pc|la\s+pc|local)\s*$",
        "",
        cmd,
    )
    cmd = re.sub(r"\s+(?:aqui|aca)\s*$", "", cmd)
    return cmd
