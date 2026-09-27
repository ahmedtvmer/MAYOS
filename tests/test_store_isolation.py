"""Structural store-isolation test for the split database modules (#78).

The folder a module lives in states which store it may touch:

- ``database/registry/`` and ``database/exercise_library/`` modules may
  reference the registry connection (``catalog_conn`` / ``_catalog_lock`` /
  ``catalog_transaction``) but never the ledger connection or active user.
- ``database/ledger/`` modules may reference the ledger connection
  (``user_conn`` / ``conn`` / ``active_user`` / ``ledger_transaction``) but
  never the registry connection or catalog lock.

Anything that needs both belongs in a top-level operation module named for the
operation (e.g. ``database/account_deletion.py``), which this test does not scan.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

REGISTRY_TOKENS = (".catalog_conn", "._catalog_lock", ".catalog_transaction")
LEDGER_TOKENS = (
    ".user_conn",
    "self.conn",
    "self.active_user",
    ".ledger_transaction",
    "._local",
)

REGISTRY_PACKAGES = ("database/registry", "database/exercise_library")
LEDGER_PACKAGE = "database/ledger"


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
