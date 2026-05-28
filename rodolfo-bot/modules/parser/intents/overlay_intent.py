from modules.parser.base_intent import BaseIntent, IntentResult

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
        if cmd in hide_phrases or any(p in cmd for p in hide_phrases):
            return IntentResult(action="hide_overlay", confidence=1.0)
        if cmd in show_phrases or any(p in cmd for p in show_phrases):
            return IntentResult(action="show_overlay", confidence=1.0)
        return None
