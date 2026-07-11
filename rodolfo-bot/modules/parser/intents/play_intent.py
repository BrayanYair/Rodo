import re
from modules.parser.base_intent import BaseIntent, IntentResult
from modules.parser.normalizer import _detect_content_type

class PlayIntent(BaseIntent):
    priority = 50
    name = "play_music"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        # Ignorar si es comando de transferencia
        _xfer_verbs = {"pasemos", "pasa", "pasalo", "pasala", "pasame", "vamos", "vamonos", "mueve", "manda", "mandame", "cambia", "trae"}
        _xfer_dest  = ["mi pc", "a la pc", "al pc", "a local", "al local", "mis parlantes", "mis altavoces", " aqui", " aca"]
        if bool(set(cmd.split()) & _xfer_verbs) and any(d in cmd for d in _xfer_dest):
            return IntentResult(action="ignored", confidence=1.0)

        # Biblioteca personal de Spotify — "mis guardadas", "mis me gusta", etc.
        if re.search(
            r"\b(?:mis|mi)\s+(?:guardadas?|me\s+gusta|favoritas?|likes?|canciones?\s+guardadas?|musicas?\s+guardadas?|temas?\s+guardados?)\b",
            cmd,
        ):
            return IntentResult(action=self.name, confidence=1.0, query="", spotify_type="saved_tracks")

        # "dime de Arcangel" suele ser STT de un titulo pedido tras el wakeword.
        # Lo tratamos como musica solo con el patron "dime de X" para no capturar
        # futuros comandos conversacionales tipo "dime que hora es".
        if re.match(r"\bdime\s+de\s+[\w\s]{2,}$", cmd):
            return IntentResult(action=self.name, confidence=0.75, query=cmd)

        play_verbs = [
            "ponme", "pon", "pone", "poner", "ponle", "ponele",
            "reproduce", "reproduceme", "reproducir", "play",
            "coloca", "colocame", "colocar",
            "echa", "echame", "tira", "tirame",
            "pongamos", "escuchemos",
            "quiero escuchar", "quiero oir", "quisiera escuchar",
            "metele", "dame", "con",
        ]

        # Verificar si comienza con algún verbo de reproducción
        for verb in play_verbs:
            if cmd == verb or cmd.startswith(verb + " "):
                rest = cmd[len(verb):].strip()
                rest = re.sub(r"^(?:me\s+)?", "", rest)

                # Detectar tipo de contenido ANTES de limpiar prefijos indicadores
                rest, spotify_type = _detect_content_type(rest)
                if not spotify_type:
                    # Sin tipo → limpiar prefijos genéricos (artículos, palabras de relleno)
                    rest = re.sub(r"^(?:la|el|un|una|los|las)\s+", "", rest)
                    rest = re.sub(r"^(?:musica|cancion|tema|rola|track|tonada)\s*(?:de\s+)?", "", rest)
                    rest = re.sub(r"^(?:de\s+)", "", rest)
                rest = re.sub(r"\s*(?:por\s+favor|porfa|porfis)\s*$", "", rest)

                # Encolar si termina con "a la cola"
                if re.search(r"\s+a\s+la\s+cola$", rest):
                    rest = re.sub(r"\s+a\s+la\s+cola$", "", rest).strip()
                    if rest and len(rest) > 1:
                        return IntentResult(action="queue_music", confidence=1.0, query=rest, spotify_type=spotify_type)

                rest = rest.strip()
                if rest and len(rest) > 1 and rest not in ("musica", "cancion", "tema", "algo", "rola"):
                    return IntentResult(action=self.name, confidence=0.95, query=rest, spotify_type=spotify_type)
                
                return IntentResult(action=self.name, confidence=0.9)

        return None
