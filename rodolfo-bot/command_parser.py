"""
command_parser.py — Fachada compatible que delega al nuevo motor modular modules/parser.
"""

from modules.parser.normalizer import normalize as _norm, strip_fillers as _fill, ACTIVATOR_NAMES, _detect_content_type
from modules.parser.stt_corrections import fix_common_stt_errors as _corr
from modules.parser.fuzzy import strip_activator as _act
from modules.parser.parser_engine import full_parse as _fp, _SHUFFLE_RE

def normalize(cmd: str) -> str:
    return _norm(cmd)

def strip_activator(cmd: str):
    return _act(cmd)

def strip_fillers(cmd: str) -> str:
    return _fill(cmd)

def fix_common_stt_errors(cmd: str) -> str:
    return _corr(cmd)

def full_parse(raw_text: str, require_activator: bool = True):
    return _fp(raw_text, require_activator)
