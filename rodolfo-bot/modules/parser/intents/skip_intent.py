import re
from modules.parser.base_intent import BaseIntent, IntentResult

class SkipIntent(BaseIntent):
    priority = 85
    name = "skip_music"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        fast_skips = {"salta", "saltala", "pasala", "pasalo", "siguiente", "skip", "salte"}
        if cmd in fast_skips:
            return IntentResult(action=self.name, confidence=1.0)
        if re.search(r"\b(salta|saltala|pasala|pasalo|siguiente|skip|salte)\b", cmd):
            return IntentResult(action=self.name, confidence=0.95)

        # Fuzzy match
        from modules.parser.fuzzy import fuzzy_match_ratio
        for w in ctx.get("words", []):
            if fuzzy_match_ratio(w, "skipea") >= 0.85 or fuzzy_match_ratio(w, "siguientes") >= 0.85:
                return IntentResult(action=self.name, confidence=0.8)

        return None
