from modules.parser.base_intent import BaseIntent, IntentResult

class DisconnectIntent(BaseIntent):
    priority = 65
    name = "disconnect_music"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        disconnect_phrases = [
            "sal del canal", "sal de la voz", "vete del canal",
            "desconectate", "desconecta bot",
            "salte de discord", "salte del discord", "sal de discord",
            "hasta luego", "chau", "chao", "adios", "nos vemos",
            "cierra discord", "sal ya"
        ]
        if cmd in disconnect_phrases or any(p in cmd for p in disconnect_phrases):
            return IntentResult(action=self.name, confidence=1.0)
        return None
