"""Aviation lexicon post-processing for ATC transcripts."""

from __future__ import annotations

import re

# Common Whisper hallucinations on airband audio
_HALLUCINATION_PATTERNS = [
    r"^\s*\[.*\]\s*$",
    r"thank you for watching",
    r"subscribe",
    r"^\s*\.\s*$",
]

_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "tree": "3",
    "three": "3",
    "four": "4",
    "fife": "5",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "niner": "9",
    "nine": "9",
    "decimal": ".",
    "point": ".",
}


def is_hallucination(text: str) -> bool:
    t = text.strip().lower()
    if len(t) < 2:
        return True
    for pat in _HALLUCINATION_PATTERNS:
        if re.search(pat, t, re.I):
            return True
    return False


def normalize_numbers(text: str) -> str:
    """Spoken digit words → digits in runway/freq/altitude contexts."""
    out = text
    for word, digit in _NUMBER_WORDS.items():
        out = re.sub(rf"\b{word}\b", digit, out, flags=re.I)
    return out


def normalize_callsign(text: str, callsign: str) -> str:
    if not callsign:
        return text
    # N12345 → spaced variants sometimes misheard
    cs = callsign.upper().strip()
    if cs and cs not in text.upper():
        # November three five bravo → N35B heuristic left to STT prompt
        pass
    return text


def postprocess(text: str, *, callsign: str = "") -> str:
    t = text.strip()
    if is_hallucination(t):
        return ""
    t = normalize_numbers(t)
    t = normalize_callsign(t, callsign)
    t = re.sub(r"\s+", " ", t)
    return t.upper() if t.isascii() else t


def guess_direction(text: str, callsign: str) -> str:
    """Heuristic: pilot transmission if callsign appears early."""
    if not callsign:
        return "unknown"
    cs = callsign.upper()
    words = text.upper().split()
    if not words:
        return "unknown"
    head = " ".join(words[:6])
    if cs in head or cs.lstrip("N") in head:
        return "pilot"
    return "atc"
