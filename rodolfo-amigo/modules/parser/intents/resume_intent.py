from modules.parser.base_intent import BaseIntent, IntentResult

class ResumeIntent(BaseIntent):
    priority = 80
    name = "resume_music"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        resume_words = {
            "sigue", "continua", "reanuda", "resume",
            "dale play", "vuelve a poner",
            "reanuda musica", "reanuda la musica",
            "continua musica", "continua la musica",
            "sigue la musica", "sigue con la musica",
        }
        if cmd in resume_words or cmd == "play":
            return IntentResult(action=self.name, confidence=1.0)
        if any(w in cmd for w in resume_words):
            return IntentResult(action=self.name, confidence=0.95)

        # Fuzzy match
        from modules.parser.fuzzy import fuzzy_match_ratio
        for w in ctx.get("words", []):
            if fuzzy_match_ratio(w, "continuar") >= 0.85 or fuzzy_match_ratio(w, "reanudar") >= 0.85:
                return IntentResult(action=self.name, confidence=0.8)

        return None
