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
    """Case-fold names and collapse punctuation, including in non-Latin scripts."""
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKC", name or "").casefold()
        if not unicodedata.category(character).startswith("M") and character != "ـ"
    )
    normalized = re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()
