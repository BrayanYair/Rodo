import re
from modules.parser.base_intent import BaseIntent, IntentResult

class QueueIntent(BaseIntent):
    priority = 70
    name = "queue_music"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        # Luego pon X
        qm = re.match(
            r"^(?:luego|despues|posteriormente|enseguida|al\s+rato|cuando\s+(?:termine|acabe))\s+"
            r"(?:pon(?:me)?|coloca(?:me)?|echa(?:me)?|metele|reproduce(?:me)?|tira(?:me)?)\s+"
            r"(.+?)$", cmd)
        if qm:
            rest = qm.group(1).strip()
            rest = re.sub(r"^(?:la|el|un|una|los|las)\s+", "", rest)
            rest = re.sub(r"^(?:musica|cancion|tema|rola|track)\s*(?:de\s+)?", "", rest)
            if rest and len(rest) > 1:
                return IntentResult(action=self.name, confidence=1.0, query=rest)

        # Encola X / agrega X
        qm2 = re.match(r"^(?:encola(?:me)?|agrega(?:me)?|agregar|mete(?:me)?|meter)\s+(.+?)$", cmd)
        if qm2:
            rest = qm2.group(1).strip()
            rest = re.sub(r"\s+(?:a\s+la\s+cola|en\s+la\s+cola|en\s+cola)$", "", rest)
            rest = re.sub(r"^(?:la|el|un|una|los|las)\s+", "", rest)
            rest = re.sub(r"^(?:musica|cancion|tema|rola)\s*(?:de\s+)?", "", rest)
            if rest and len(rest) > 1:
                return IntentResult(action=self.name, confidence=1.0, query=rest)

        return None
