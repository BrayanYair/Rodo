import re
from modules.parser.base_intent import BaseIntent, IntentResult

class RemoveLastIntent(BaseIntent):
    priority = 70
    name = "remove_last"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        if re.search(
            r"\b(elimina|eliminar|borra|borrar|quita|quitar|saca|sacar|elimino|elimine|borro|quito|saco)\s+(?:la\s+)?ultima\b", 
            cmd
        ):
            return IntentResult(action=self.name, confidence=1.0)
            
        remove_phrases = [
            "quita esa cancion", "quita esa", "saca esa cancion",
            "borra esa cancion", "elimina esa cancion",
            "elimina la cancion que acabo", "saca la ultima"
        ]
        if cmd in remove_phrases or any(p in cmd for p in remove_phrases):
            return IntentResult(action=self.name, confidence=0.95)
        return None
