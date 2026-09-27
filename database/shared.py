"""Shared constants and errors for the split DatabaseManager modules (#78).

These names are re-exported from :mod:`database.database_manager` so existing
importers keep working (e.g. ``from database.database_manager import LedgerDeletedError``).
"""
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CSV_PATH = BASE_DIR / "data" / "processed_exercises.csv"


class LedgerDeletedError(RuntimeError):
    """Raised when a request tries to mount a ledger whose account was deleted.

    The durable deletion record wins over a ledger file that an in-flight
    request (or a stray copy) could otherwise recreate after deletion (ADR 039).
    """


def _normalize_exercise_name(name: str) -> str:
    """Lowercase and collapse punctuation so "push up" ≡ "push-up" and "two arm" ≡ "two-arm"."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
