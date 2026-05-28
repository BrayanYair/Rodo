import re
from modules.parser.base_intent import BaseIntent, IntentResult

class StopIntent(BaseIntent):
    priority = 100
    name = "stop_music"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        # 1. Coincidencias rápidas exactas
        fast_stops = {"stop", "para", "deten", "detener", "detenga", "alto", "basta", "pare", "paren",
                      "callate", "callense", "calla", "cierra", "silenciate"}
        if cmd in fast_stops:
            return IntentResult(action=self.name, confidence=1.0)

        # 2. Si todas las palabras del comando son palabras de parada (ej: "stop stop", "para para")
        words = ctx.get("words", [])
        if words and all(w in fast_stops for w in words):
            return IntentResult(action=self.name, confidence=1.0)

        # 3. Expresiones compuestas de parada
        if re.search(
            r"\b(stop|deten|detener|detenga|detiene|para|parar|pare|paren)\b.*\b(musica|cancion|tema|todo|esto|esta|reproduccion)\b", 
            cmd
        ):
            return IntentResult(action=self.name, confidence=1.0)

        if re.search(r"\b(callate|callense|calla|cierra|silenciate)\b", cmd):
            return IntentResult(action=self.name, confidence=1.0)

        # 4. Fuzzy match fallback
        from modules.parser.fuzzy import fuzzy_match_ratio
        for w in words:
            if fuzzy_match_ratio(w, "detente") >= 0.85 or fuzzy_match_ratio(w, "silencio") >= 0.85:
                return IntentResult(action=self.name, confidence=0.8)

        return None
