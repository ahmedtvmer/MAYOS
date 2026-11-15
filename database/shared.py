"""Shared constants and errors for the split DatabaseManager modules (#78).

These names are re-exported from :mod:`database.database_manager` so existing
importers keep working (e.g. ``from database.database_manager import LedgerDeletedError``).
"""
import re
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CSV_PATH = BASE_DIR / "data" / "processed_exercises.csv"


class LedgerDeletedError(RuntimeError):
    """Raised when a request tries to mount a ledger whose account was deleted.

    The durable deletion record wins over a ledger file that an in-flight
    request (or a stray copy) could otherwise recreate after deletion (ADR 039).
    """


def _normalize_exercise_name(name: str) -> str:
    """Fold name spelling, punctuation, diacritics, and common plural endings."""
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKC", name or "").casefold()
        if not unicodedata.category(character).startswith("M") and character != "\u0640"
    )
    folded = folded.translate(str.maketrans({
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
    }))
    words = re.sub(r"[\W_]+", " ", folded, flags=re.UNICODE).split()
    return " ".join(_singularize_exercise_token(word) for word in words)


def _singularize_exercise_token(token: str) -> str:
    if token.isascii() and token.isalpha():
        if token == "abs":
            return token
        if len(token) > 4 and token.endswith("ies"):
            return token[:-3] + "y"
        if len(token) > 4 and token.endswith("yes") and token[-4] not in "aeiou":
            return token[:-2]
        if len(token) > 4 and token.endswith(("sses", "ches", "shes", "xes")):
            return token[:-2]
        if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
            return token[:-1]
        return token
    if token in {"تمارين", "تمرينات"}:
        return "تمرين"
    return token
