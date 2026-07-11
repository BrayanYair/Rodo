import re
from modules.parser.base_intent import BaseIntent, IntentResult

def _has_phrase(cmd: str, phrases: list[str]) -> bool:
    """Match por palabra completa (evita que 'sal' matchee dentro de 'salsa')."""
    return any(re.search(rf"\b{re.escape(p)}\b", cmd) for p in phrases)

class OverlayIntent(BaseIntent):
    priority = 65
    name = "overlay_control"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        hide_phrases = [
            "ocultate", "oculta", "escondete", "esconde",
            "sal de mi pantalla", "sal de la pantalla", "quitate de la pantalla",
            "quitate", "desaparece", "vete de la pantalla",
            "no te veo", "escondete de mi pantalla"
        ]
        show_phrases = [
            "muestrate", "muestra", "aparece", "donde estas",
            "donde te fuiste", "vuelve a aparecer", "aparece en pantalla",
            "sal", "asomarte"
        ]
        if _has_phrase(cmd, hide_phrases):
            return IntentResult(action="hide_overlay", confidence=1.0)
        if _has_phrase(cmd, show_phrases):
            return IntentResult(action="show_overlay", confidence=1.0)
        return None
