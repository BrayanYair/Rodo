import re


def fix_common_stt_errors(cmd: str) -> str:
    """Corrige errores frecuentes de reconocimiento de voz."""
    cmd = re.sub(r"\bpom\b", "pon", cmd)
    cmd = re.sub(r"\bpong\b", "pon", cmd)
    cmd = re.sub(r"\bbong\b", "pon", cmd)
    cmd = re.sub(r"\bporn\b", "pon", cmd)
    cmd = re.sub(r"\bpum\b", "pon", cmd)
    cmd = re.sub(r"\bpomp[oó]n\b", "pon", cmd)
    cmd = re.sub(r"\bpompom\b", "pon", cmd)
    cmd = re.sub(r"\bpun\b", "pon", cmd)
    cmd = re.sub(r"\bstock\b", "stop", cmd)
    cmd = re.sub(r"\bdetente\b", "deten", cmd)
    cmd = re.sub(r"\bskype\b", "skip", cmd)

    # Variantes habituales de "oye rodo" en Google STT.
    cmd = re.sub(r"\boie\s+(?:rodo|rodolfo)\b", "oye rodo", cmd)
    cmd = re.sub(r"\b(?:que|okay)\s+(?:rodo|rodolfo)\b", "oye rodo", cmd)
    cmd = re.sub(r"\boye\s+(?:todo|lodo|rolo|robo|rodoox|roblox|rodolfo|redolfo|adolfo)\b", "oye rodo", cmd)
    cmd = re.sub(r"\brodoox\b", "rodo", cmd)
    cmd = re.sub(r"\broblox\b", "rodo", cmd)
    cmd = re.sub(r"\bredolfo\b", "rodolfo", cmd)
    cmd = re.sub(r"\badolfo\b", "rodolfo", cmd)
    cmd = re.sub(r"\brolfo\b", "rodolfo", cmd)
    cmd = re.sub(r"\brodolfof\b", "rodolfo", cmd)

    # Corregir "para" por "pon" cuando no es una orden de parada.
    if not re.search(
        r"\bpara\s+(?:la\s+)?(?:musica|cancion|tema|reproduccion|esto|eso|todo)\b", cmd
    ):
        cmd = re.sub(r"\bpara\s+(mi|el|la|un|una|algo|musica\s+de)\b", r"pon \1", cmd)

    # Limpieza de sufijos redundantes.
    cmd = re.sub(r"\s+(?:en|de)\s+(?:spotify|youtube|yt|deezer)\s*$", "", cmd)
    cmd = re.sub(
        r"\s+(?:en|a|por)\s+(?:mis\s+)?"
        r"(?:parlantes|altavoces|bocinas|mi\s+pc|la\s+pc|local)\s*$",
        "",
        cmd,
    )
    cmd = re.sub(r"\s+(?:aqui|aca)\s*$", "", cmd)
    return cmd
