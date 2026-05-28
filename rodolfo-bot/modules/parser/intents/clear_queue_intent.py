import re
from modules.parser.base_intent import BaseIntent, IntentResult

class ClearQueueIntent(BaseIntent):
    priority = 70
    name = "clear_queue"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        if re.search(
            r"\b(?:elimina(?:r)?|borra(?:r)?|quita(?:r)?|vacia(?:r)?|limpia(?:r)?)\s+"
            r"(?:tod[ao]s?\s+)?(?:la\s+|las\s+|el\s+)?(?:cola|lista|canciones|temas)\b", 
            cmd
        ):
            return IntentResult(action=self.name, confidence=1.0)
            
        clear_phrases = {
            "limpia la cola", "limpiar cola", "limpia cola",
            "limpia la lista", "limpiar lista", "limpia lista",
            "vacia la cola", "vaciar cola", "vacia cola",
            "vacia la lista", "vaciar lista", "vacia lista",
            "borra la cola", "borrar cola", "borra cola",
            "borra la lista", "borrar lista", "borra lista",
            "quita la cola", "quitar la cola",
            "quita la lista", "quitar la lista",
            "quita todo de la cola", "quita todas las canciones de la cola",
            "quita las canciones de la cola",
            "elimina la cola", "eliminar cola", "elimina cola",
            "elimina la lista", "eliminar lista", "elimina lista",
            "elimino la lista", "eligio la lista",
            "eliminan la lista", "eliminan la cola", "eliminan"
        }
        if cmd in clear_phrases or any(p in cmd for p in clear_phrases):
            return IntentResult(action=self.name, confidence=0.95)
        return None
