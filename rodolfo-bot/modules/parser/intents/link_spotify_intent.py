import re
from modules.parser.base_intent import BaseIntent, IntentResult

class LinkSpotifyIntent(BaseIntent):
    priority = 65
    name = "link_spotify"

    def match(self, cmd: str, ctx: dict) -> IntentResult | None:
        if re.search(
            r"\b(?:vincula(?:me)?|conecta(?:me)?|link|enlaza(?:me)?)\b.{0,20}\bspotify\b",
            cmd
        ):
            return IntentResult(action=self.name, confidence=1.0)
        return None
