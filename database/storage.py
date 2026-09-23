"""Persistent data-root resolution and fail-closed storage validation.

Local development keeps the historical ``<repo>/db`` layout. In a container the
``MAYOS_DATA_DIR`` env points at the mounted Fly volume (``/data``) so the
catalog, per-user ledgers, and the migration/backup work area all live on
durable storage from boot, seeding, the reset CLI, and normal requests.

Setting ``MAYOS_REQUIRE_PERSISTENT_DATA=true`` additionally requires the data
root to be a real mount point and writable. That makes a missing or unwritable
volume fail closed at startup/readiness instead of silently writing the catalog
and ledgers onto the container's ephemeral filesystem.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

DATA_ROOT_ENV = "MAYOS_DATA_DIR"
REQUIRE_PERSISTENT_ENV = "MAYOS_REQUIRE_PERSISTENT_DATA"
_WRITE_PROBE_PREFIX = ".mayos-write-probe-"

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = BASE_DIR / "db"


class StorageNotReady(RuntimeError):
    """Raised when the configured persistent data root cannot be used safely."""


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def configured_data_root() -> Path | None:
    """The explicit ``MAYOS_DATA_DIR`` root, or ``None`` in local-default mode."""
    raw = os.getenv(DATA_ROOT_ENV, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def require_persistent_data() -> bool:
    """True when the configured root must be a real mount (production)."""
    return _env_truthy(REQUIRE_PERSISTENT_ENV)


def resolve_data_root() -> Path:
    """Data root for path defaults: ``MAYOS_DATA_DIR`` when set, else ``<repo>/db``."""
    return configured_data_root() or DEFAULT_DATA_ROOT


def validate_data_root() -> Path:
    """Fail-closed boot check for the configured data root.

    Only meaningful when ``MAYOS_DATA_DIR`` is set; local-default mode returns
    the repo ``db`` directory untouched so existing dev runs and tests are
    unchanged. Raises :class:`StorageNotReady` when the root is missing, is not
    a directory, is not writable, fails a write probe, or is not a mount while
    persistence is required.
    """
    root = configured_data_root()
    if root is None:
        return DEFAULT_DATA_ROOT
    if not root.exists():
        raise StorageNotReady(f"MAYOS_DATA_DIR '{root}' does not exist; the persistent volume is not mounted.")
    if not root.is_dir():
        raise StorageNotReady(f"MAYOS_DATA_DIR '{root}' is not a directory.")
    if not os.access(root, os.W_OK):
        raise StorageNotReady(f"MAYOS_DATA_DIR '{root}' is not writable.")
    if require_persistent_data() and not os.path.ismount(root):
        raise StorageNotReady(
            f"MAYOS_DATA_DIR '{root}' is not a mount point; refusing to write to ephemeral container storage."
        )
    _probe_writable(root)
    return root


def _probe_writable(root: Path) -> None:
    """Confirm the root accepts a new file without leaving anything behind."""
    try:
        fd, probe = tempfile.mkstemp(prefix=_WRITE_PROBE_PREFIX, dir=root)
    except OSError as exc:
        raise StorageNotReady(f"MAYOS_DATA_DIR '{root}' failed a write probe: {exc}") from exc
    try:
        os.close(fd)
    finally:
        try:
            os.unlink(probe)
        except OSError:
            pass


def storage_status() -> tuple[bool, str]:
    """Readiness view used by ``/readyz``.

    Delegates to :func:`validate_data_root` (including its write probe) so a
    root that becomes unwritable after boot flips readiness to not-ready instead
    of staying green. Local-default mode (no ``MAYOS_DATA_DIR``) is always ready.
    """
    if configured_data_root() is None:
        return True, "local-default"
    try:
        validate_data_root()
    except StorageNotReady:
        return False, "data-dir-not-ready"
    return True, "ok"
