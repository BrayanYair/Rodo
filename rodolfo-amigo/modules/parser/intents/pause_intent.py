import re
from modules.parser.base_intent import BaseIntent, IntentResult

class PauseIntent(BaseIntent):
    priority = 90
    name = "pause_music"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        if cmd in ("pausa", "pausala"):
            return IntentResult(action=self.name, confidence=1.0)
        if re.search(r"\b(pausa|pausala)\b", cmd):
            return IntentResult(action=self.name, confidence=0.95)

        # Fuzzy match
        from modules.parser.fuzzy import fuzzy_match_ratio
        for w in ctx.get("words", []):
            if fuzzy_match_ratio(w, "pausar") >= 0.85 or fuzzy_match_ratio(w, "pausalo") >= 0.85:
                return IntentResult(action=self.name, confidence=0.8)

        return None
