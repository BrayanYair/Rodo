from modules.parser.base_intent import BaseIntent, IntentResult

class HelpIntent(BaseIntent):
    priority = 60
    name = "help"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        help_phrases = [
            "ayuda", "help", "comandos", "que sabes hacer", "que puedes hacer",
            "como te uso", "que haces", "dime tus comandos", "dime los comandos"
        ]
        if cmd in help_phrases or any(p in cmd for p in help_phrases):
            return IntentResult(action=self.name, confidence=1.0)
        return None
