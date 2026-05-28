from dataclasses import dataclass, field
import typing

@dataclass
class IntentResult:
    action: str
    confidence: float
    query: str = ""
    spotify_type: typing.Optional[str] = None
    shuffle: bool = False
    metadata: dict = field(default_factory=dict)

class BaseIntent:
    priority: int = 0
    name: str = "base"

    def match(self, cmd: str, ctx: dict) -> typing.Optional[IntentResult]:
        raise NotImplementedError("Debe implementar el método match")
