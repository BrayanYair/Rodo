from modules.parser.base_intent import BaseIntent, IntentResult

class StatusIntent(BaseIntent):
    priority = 75
    name = "music_status"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        status_phrases = [
            "que esta sonando", "que cancion es", "que suena",
            "como se llama esta", "que tema es", "que estoy escuchando",
            "cancion actual"
        ]
        if cmd in status_phrases:
            return IntentResult(action=self.name, confidence=1.0)
        if any(phrase in cmd for phrase in status_phrases):
            return IntentResult(action=self.name, confidence=0.95)
        return None
