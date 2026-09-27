"""Glossary guard: legacy trainee / ledger wording must not come back (#80).

CONTEXT.md calls the account holder a **Player**, their private record a
**Training ledger**, and the shared reference set an **Exercise library**. This
test fails when backend code under ``database/``, ``service/`` or ``agent/``
reintroduces the legacy terms as identifiers or as prose.

Wire and storage names are intentionally exempt: HTTP JSON fields such as
``"trainee_id"``, the ``trainee_emails`` / ``password_reset_tokens`` SQL
columns, graph-state keys stored in the checkpointer, and persisted profile
keys may keep their historical spelling. Those are *strings*, so the identifier
scan below never sees them; only Python names are checked.
"""

import io
import os
import re
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNED_PACKAGES = ("database", "service", "agent")

#: User-visible text kept from HEAD on purpose. Changing any of these literals
#: is a behaviour change, not a rename, so the wording guard must not flag them.
#: The expected wrappers around a user-visible string are allowlisted here.
ALLOWED_USER_VISIBLE_TEXT: dict[str, set[str]] = {
    "agent/ProgramState.py": {
        "Execution steps from the exercise catalog (or a chat-supplied cue)",
    },
    "agent/assistant_graph.py": {
        "Failed to search the exercise catalog.",
    },
    "service/auth.py": {
        "Trainee ID is empty after sanitization.",
        "This Trainee ID already exists. Please log in.",
        "Trainee ledger not found.",
    },
    "service/password_reset.py": {
        "Trainee ledger not found.",
    },
}

#: The only ``trainee_id`` identifiers allowed: the LangGraph state field
#: annotations. They mirror the persisted checkpointer key ``"trainee_id"`` (and
#: the request/response JSON field of the same name), so the annotation must
#: match the stored key. Each regex targets the specific field line, not the
#: whole file.
ALLOWED_TRAINEE_ID_FIELDS = {
    "agent/assistant_graph.py": re.compile(r"^\s*trainee_id:\s*str\s*$"),
    "agent/onboarding_graph.py": re.compile(r"^\s*trainee_id:\s*str \| None\s*$"),
}

#: Identifiers the glossary rename removed: "user" named the player's ledger,
#: "trainee" named the player, and "exercise catalog" became exercise library.
#: Replacements are ledger_conn / create_ledger_schema / backup_ledger /
#: ledger_id / ledgers_dir / ledger_exists / register_player /
#: get_current_player / get_player_profile / PlayerProfileSchema /
#: get_account_email / get_exercise_library_entry and friends.
LEGACY_IDENTIFIERS = {
    # user → ledger
    "user_conn",
    "create_user_schema",
    "_create_user_schema_on",
    "backup_active_user",
    "active_user",
    "users_dir",
    "DEFAULT_USERS_DIR",
    "user_db_path",
    "user_exists",
    "prune_user_backups",
    "user_backup_dir",
    "CURRENT_USER_SCHEMA_VERSION",
    "get_user_schema_version",
    "set_user_schema_version",
    # user profile → player profile
    "get_user_profile",
    "upsert_user_profile",
    "clear_user_profile",
    "update_user_persona",
    "update_user_frequency",
    "UserProfileSchema",
    # trainee → player
    "register_trainee",
    "login_trainee",
    "claim_trainee",
    "get_current_trainee",
    "simulate_trainee_session",
    "get_trainee_email",
    "set_trainee_email",
    "get_trainee_by_email",
    # exercise catalog → exercise library
    "get_exercise_catalog_entry",
    "get_exercise_catalog_detail",
    "read_exercise_catalog_detail",
}

#: Banned prose, matched case-insensitively anywhere in the scanned source
#: (including comments and docstrings). ``exercise_catalog`` keeps no word
#: boundaries so it also catches ``get_exercise_catalog_entry``: ``_`` is a word
#: character, so ``\bexercise_catalog\b`` would never match it.
BANNED_PHRASES = (
    r"\buser database\b",
    r"\buser db\b",
    r"\bexercise catalog\b",
    r"exercise_catalog",
)


def _scanned_files():
    for package in SCANNED_PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def _identifier_tokens(source: str):
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.NAME:
            yield token


def _is_allowed_trainee_id_field(relative: str, name: str, line: str) -> bool:
    pattern = ALLOWED_TRAINEE_ID_FIELDS.get(relative)
    return name == "trainee_id" and pattern is not None and pattern.match(line) is not None


@pytest.mark.parametrize("path", list(_scanned_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_trainee_identifiers(path):
    relative = str(path.relative_to(ROOT))
    lines = path.read_text().splitlines()
    offenders = sorted(
        {
            token.string
            for token in _identifier_tokens(path.read_text())
            if "trainee" in token.string.lower()
            and not _is_allowed_trainee_id_field(relative, token.string, lines[token.start[0] - 1])
        }
    )
    assert not offenders, f"{relative} reintroduced trainee identifiers: {offenders}"


@pytest.mark.parametrize("path", list(_scanned_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_legacy_identifiers(path):
    relative = str(path.relative_to(ROOT))
    names = {token.string for token in _identifier_tokens(path.read_text())}
    offenders = sorted(name for name in names if name in LEGACY_IDENTIFIERS)
    assert not offenders, f"{relative} reintroduced legacy identifiers: {offenders}"


@pytest.mark.parametrize("path", list(_scanned_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_banned_legacy_wording(path):
    relative = str(path.relative_to(ROOT))
    source = path.read_text()
    # User-visible text is behaviour, not naming: drop the allowlisted literals
    # before scanning so only newly reintroduced legacy prose is flagged.
    for literal in ALLOWED_USER_VISIBLE_TEXT.get(relative, set()):
        source = source.replace(literal, "")
    offenders = [pattern for pattern in BANNED_PHRASES if re.search(pattern, source, re.IGNORECASE)]
    assert not offenders, f"{relative} reintroduced legacy wording: {offenders}"


def test_scanned_packages_exist_and_have_files():
    files = list(_scanned_files())
    assert files, "glossary guard scanned no files; check SCANNED_PACKAGES"
    assert os.path.isdir(ROOT / "database")
