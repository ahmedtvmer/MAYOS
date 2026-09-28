"""Structural store-isolation test for the split database modules (#78, #79).

The folder a module lives in states which store it may touch:

- ``database/registry/`` and ``database/exercise_library/`` modules may
  reference the registry connection (``catalog_conn`` / ``_catalog_lock`` /
  ``catalog_transaction``) but never the ledger connection or ledger id.
- ``database/ledger/`` modules may reference the ledger connection
  (``ledger_conn`` / ``conn`` / ``ledger_id`` / ``ledger_transaction``) but
  never the registry connection or catalog lock.

Anything that needs both belongs in a top-level operation module named for the
operation (e.g. ``database/account_deletion.py``), which this test does not scan.

Phase B2 (#79): the thread-local ledger mount and the ``database/store.py``
context-local provider are gone. Every ledger is reached through an explicit
:class:`~database.ledger.handle.TrainingLedger` from
``DatabaseManager.open_ledger``; registry work stays on the app store, which is
passed explicitly. No production module may import ``bind_user`` /
``switch_user`` / ``active_user`` / ``unmount_user`` / ``bind_request`` /
``get_store`` / ``set_store`` again, and no store may be constructed at import
time.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

REGISTRY_TOKENS = (".catalog_conn", "._catalog_lock", ".catalog_transaction")
LEDGER_TOKENS = (
    ".ledger_conn",
    "self.conn",
    "self.ledger_id",
    ".ledger_transaction",
    "._local",
)

REGISTRY_PACKAGES = ("database/registry", "database/exercise_library")
LEDGER_PACKAGE = "database/ledger"

#: Seams removed with the thread-local mount and the ambient store provider.
REMOVED_SEAMS = (
    "bind_user",
    "bind_request",
    "switch_user",
    "unmount_user",
    "active_user",
    "get_store",
    "set_store",
    "reset_store",
)

#: Production layers that must never reach for a removed seam again.
LAYER_PACKAGES = ("agent", "service", "svc", "database", "scripts", "utils")

#: A ledger-internal module may keep ``self.ledger_id``; nothing else may read
#: a ledger handle through the store.
LEDGER_INTERNAL_PREFIX = Path("database/ledger")

#: Store/DatabaseManager attributes the test-only ``conftest`` facade adds for
#: pre-split tests. Production code must reach a ledger through an explicit
#: ``open_ledger`` handle, never off the store. ``_test_ledger_id`` is
#: deliberately distinctive so production reading a store's ``ledger_id``
#: cannot masquerade as the facade.
STORE_FACADE_TOKENS = (".ledger_conn", "._test_ledger_id")

#: ``.conn`` is a ledger handle's own accessor. It is legitimate when the
#: receiver is a ``TrainingLedger`` (program rules, dashboard reads, the init
#: script) or a ledger handle passed through a parameter still typed
#: ``DatabaseManager`` (``progression_engine``); those files are listed here
#: rather than banning ``.conn`` outright.
CONN_ALLOWLIST = frozenset({
    "agent/program_rules.py",
    "agent/progression_engine.py",
    "service/dashboard.py",
    "service/workouts.py",
    "scripts/intialize_db.py",
})

#: Layers scanned for reads of the test-only store facade. ``database/ledger/``
#: is skipped there because ``self.conn`` / ``self.ledger_id`` are the handle's
#: own state.
STORE_FACADE_PACKAGES = LAYER_PACKAGES

#: A module-level ``DatabaseManager(...)`` construction (no indentation).
MODULE_LEVEL_STORE = re.compile(r"^[A-Za-z_][\w]*\s*=\s*DatabaseManager\(")

PHASE_B2_MARKER = "# Phase B2:"


def _modules(package: str) -> list[Path]:
    return sorted((ROOT / package).rglob("*.py"))


def _references(source: str, tokens: tuple[str, ...]) -> list[str]:
    return [token for token in tokens if token in source]


@pytest.mark.parametrize("package", REGISTRY_PACKAGES)
def test_registry_and_library_modules_never_touch_the_ledger(package):
    for path in _modules(package):
        source = path.read_text()
        offenders = _references(source, LEDGER_TOKENS)
        assert not offenders, f"{path.relative_to(ROOT)} references ledger state: {offenders}"


def test_ledger_modules_never_touch_the_registry():
    for path in _modules(LEDGER_PACKAGE):
        source = path.read_text()
        offenders = _references(source, REGISTRY_TOKENS)
        assert not offenders, f"{path.relative_to(ROOT)} references registry state: {offenders}"


def _uses_token(source: str, token: str) -> bool:
    """Whole-word match so ``active_username`` never trips the seam checks."""
    return re.search(rf"\b{re.escape(token)}\b", source) is not None


def _reads_stored_ledger(source: str) -> bool:
    """True when source reads ``.ledger`` as an attribute, not the package path.

    ``database.ledger.handle`` in imports/docstrings is a module path, not a
    store attribute, so the ``database`` prefix is excluded.
    """
    return re.search(r"(?<!database)\.ledger\b(?!\.)", source) is not None


@pytest.mark.parametrize("package", STORE_FACADE_PACKAGES)
def test_layers_never_use_the_test_only_store_facade(package):
    """Production reaches the ledger via ``open_ledger``, never store attributes.

    ``.ledger`` / ``.ledger_conn`` / ``._test_ledger_id`` are added to a store
    only by the test ``conftest`` facade; reading them in production would mean
    the thread-local mount crept back. ``.conn`` on a ledger handle stays
    legitimate and is allow-listed per file.
    """
    for path in _modules(package):
        relative = path.relative_to(ROOT)
        if str(relative).startswith(str(LEDGER_INTERNAL_PREFIX)):
            continue
        source = path.read_text()
        offenders = [token for token in STORE_FACADE_TOKENS if _uses_token(source, token)]
        if _reads_stored_ledger(source):
            offenders.append(".ledger")
        assert not offenders, (
            f"{relative} reads a test-only store facade attribute: {offenders}"
        )
        if str(relative) not in CONN_ALLOWLIST:
            assert not _uses_token(source, ".conn"), (
                f"{relative} calls .conn off a store; open a ledger handle instead"
            )


@pytest.mark.parametrize("package", LAYER_PACKAGES)
def test_no_removed_ledger_seams_remain(package):
    for path in _modules(package):
        relative = path.relative_to(ROOT)
        source = path.read_text()
        offenders = [token for token in REMOVED_SEAMS if _uses_token(source, token)]
        assert not offenders, f"{relative} uses a removed ledger seam: {offenders}"


@pytest.mark.parametrize("package", LAYER_PACKAGES)
def test_no_phase_b2_markers_remain(package):
    for path in _modules(package):
        source = path.read_text()
        assert PHASE_B2_MARKER not in source, f"{path.relative_to(ROOT)} still carries a Phase B2 marker"


@pytest.mark.parametrize("package", LAYER_PACKAGES)
def test_no_module_level_database_manager_instances(package):
    for path in _modules(package):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            assert not MODULE_LEVEL_STORE.match(line), (
                f"{path.relative_to(ROOT)}:{lineno} constructs a module-level DatabaseManager"
            )
