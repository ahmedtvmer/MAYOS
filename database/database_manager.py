import os
import re
import sqlite3
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import sqlite_vec

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.storage import configured_data_root, resolve_data_root, validate_data_root

#: Catalog, ledgers and backups all hang off one data root (``MAYOS_DATA_DIR``).
_DATA_ROOT = resolve_data_root()
DEFAULT_CATALOG_PATH = _DATA_ROOT / "catalog.db"
DEFAULT_LEDGERS_DIR = _DATA_ROOT / "users"
DEFAULT_BACKUPS_DIR = _DATA_ROOT / "backups"

from database.migration_manager import apply_lazy_migrations, prune_ledger_backups
from utils.logger import MyosLogger

from database.schema.definitions import EMBEDDING_DIM as CATALOG_EMBEDDING_DIM
from database.schema.definitions import SchemaMixin
from database.account_deletion import AccountDeletionMixin
from database.registry.accounts import RegistryAccountsMixin
from database.registry.linked_sign_ins import RegistryLinkedSignInsMixin
from database.registry.plans import RegistryPlansMixin
from database.registry.recovery import RegistryRecoveryMixin
from database.registry.coach_invites import RegistryCoachInvitesMixin
from database.registry.assignments import RegistryAssignmentsMixin
from database.registry.program_requests import RegistryProgramRequestsMixin
from database.registry.coach_alerts import RegistryCoachAlertsMixin
from database.registry.check_ins import RegistryCheckInsMixin
from database.registry.model_usage import RegistryModelUsageMixin
from database.exercise_library.lookup import ExerciseLookupMixin
from database.exercise_library.schema import EXERCISE_COLUMNS, effective_exercise_name_sql
from database.exercise_library.similarity import ExerciseSimilarityMixin
from database.exercise_library.seeding import ExerciseSeedingMixin
from database.ledger.handle import TrainingLedger

logger = MyosLogger().get_logger(__name__)

# Re-exported so existing importers keep working after the module split (#78).
from database.shared import LedgerDeletedError
from database.shared import DEFAULT_CSV_PATH as DEFAULT_CSV_PATH  # noqa: F401  (re-export)
from database.shared import _normalize_exercise_name as _normalize_exercise_name  # noqa: F401


class DatabaseManager(
    SchemaMixin,
    AccountDeletionMixin,
    RegistryAccountsMixin,
    RegistryLinkedSignInsMixin,
    RegistryPlansMixin,
    RegistryRecoveryMixin,
    RegistryCoachInvitesMixin,
    RegistryAssignmentsMixin,
    RegistryProgramRequestsMixin,
    RegistryCoachAlertsMixin,
    RegistryCheckInsMixin,
    RegistryModelUsageMixin,
    ExerciseLookupMixin,
    ExerciseSimilarityMixin,
    ExerciseSeedingMixin,
):
    EMBEDDING_DIM = CATALOG_EMBEDDING_DIM

    def __init__(
        self,
        catalog_path=None,
        ledgers_dir=None,
        backups_dir=None,
        default_ledger_id: str | None = None,
        deletions_path=None,
    ):
        if configured_data_root() is not None:
            root = validate_data_root()
        else:
            root = resolve_data_root()
        self.catalog_path = Path(catalog_path) if catalog_path is not None else root / "catalog.db"
        self.ledgers_dir = Path(ledgers_dir) if ledgers_dir is not None else root / "users"
        self.backups_dir = Path(backups_dir) if backups_dir is not None else root / "backups"
        # The API and operational scripts inject the configured off-site store.
        # Keeping the default unset preserves hermetic local-only/test stores.
        self.offsite_backup = None
        env_deletions = os.getenv("MAYOS_DELETIONS_DB", "").strip()
        if deletions_path is not None:
            self.deletions_path = Path(deletions_path)
        elif env_deletions:
            self.deletions_path = Path(env_deletions)
        else:
            self.deletions_path = self.catalog_path.parent / "deletions.db"
        # The default ledger id is a convenience for tests/scripts that want a
        # stable id to open explicitly; the store itself mounts nothing (ADR 041).
        self.default_ledger_id = self._sanitize_username(default_ledger_id) if default_ledger_id else "default"
        self._catalog_lock = threading.RLock()
        # Catalog transaction depth is per-instance and per-thread. There is no
        # mounted-ledger state on the store: ledgers live on explicit handles.
        self._local = threading.local()

        os.makedirs(self.catalog_path.parent, exist_ok=True)
        os.makedirs(self.ledgers_dir, exist_ok=True)
        os.makedirs(self.backups_dir, exist_ok=True)

        self.catalog_conn = sqlite3.connect(self.catalog_path, check_same_thread=False)
        self.catalog_conn.execute("PRAGMA foreign_keys = ON;")
        self.catalog_conn.execute("PRAGMA journal_mode = WAL;")
        self.catalog_conn.execute("PRAGMA busy_timeout = 5000;")
        self.catalog_conn.execute("PRAGMA synchronous = NORMAL;")
        self.catalog_conn.enable_load_extension(True)
        sqlite_vec.load(self.catalog_conn)
        self.catalog_conn.enable_load_extension(False)

        self.create_catalog_schema()

        self._initialize_deletions()

        logger.info("DatabaseManager initialized; ledgers are opened as explicit handles.")

    @staticmethod
    def _sanitize_username(username: str) -> str:
        clean = re.sub(r"[^\w\-]", "", str(username).strip().lower())
        return clean or "default"

    def _build_ledger_connection(self, sanitized: str) -> sqlite3.Connection:
        """Opens, migrates and returns a ledger connection for a sanitized id.

        The connect/pragma/attach/migrate sequence lives here once; ``open_ledger``
        wraps the result in a :class:`~database.ledger.handle.TrainingLedger`.
        """
        ledger_db_path = self.ledgers_dir / f"{sanitized}.db"
        new_conn = sqlite3.connect(ledger_db_path, check_same_thread=False)
        new_conn.row_factory = sqlite3.Row
        new_conn.execute("PRAGMA foreign_keys = ON;")
        new_conn.execute("PRAGMA journal_mode = WAL;")
        new_conn.execute("PRAGMA busy_timeout = 5000;")
        new_conn.execute("PRAGMA synchronous = NORMAL;")

        escaped_path = str(self.catalog_path.resolve()).replace("'", "''")
        new_conn.execute(f"ATTACH DATABASE '{escaped_path}' AS catalog;")
        self._create_ledger_exercise_view(new_conn)
        new_conn.execute(
            "CREATE TEMP VIEW IF NOT EXISTS exercise_secondary_muscles AS SELECT * FROM catalog.exercise_secondary_muscles;"
        )

        apply_lazy_migrations(new_conn, sanitized, self.ledgers_dir, self.backups_dir)
        self._create_ledger_schema_on(new_conn)
        prune_ledger_backups(self.backups_dir / sanitized, max_rolling=3)
        return new_conn

    @staticmethod
    def _create_ledger_exercise_view(conn: sqlite3.Connection) -> None:
        name_expression, display_name_join = effective_exercise_name_sql("catalog")
        selected_columns = [
            f"{name_expression} AS name" if column == "name" else f"e.{column}"
            for column in EXERCISE_COLUMNS
        ]
        conn.execute(
            "CREATE TEMP VIEW IF NOT EXISTS exercises AS "
            f"SELECT {', '.join(selected_columns)} FROM catalog.exercises e {display_name_join}"
        )

    def open_ledger(self, ledger_id: str) -> "TrainingLedger":
        """Opens an explicit ledger handle for ``ledger_id`` (ADR 041, phase B).

        Runs the deleted-ledger gate and the mount work (pragmas, catalog attach,
        lazy migrations, ledger schema, backup pruning) and returns a
        :class:`~database.ledger.handle.TrainingLedger` owning its own connection.
        Use it as a context manager so it closes on exit.
        """
        sanitized = self._sanitize_username(ledger_id)
        if not sanitized:
            raise ValueError("A ledger id is required to open a ledger.")
        if self._ledger_is_deleted(sanitized):
            logger.warning(f"Refusing to open deleted ledger '{sanitized}'.")
            raise LedgerDeletedError(f"Ledger '{sanitized}' belongs to a deleted account.")
        return TrainingLedger(self._build_ledger_connection(sanitized), sanitized, self.backups_dir)

    @contextmanager
    def catalog_locked(self) -> Iterator[sqlite3.Connection]:
        """Yields the shared catalog connection under the catalog lock.

        All direct catalog reads must go through this helper; the raw
        ``catalog_conn`` cursor is not thread-safe on its own.
        """
        with self._catalog_lock:
            yield self.catalog_conn

    # Catalog transactions: re-entrant, catalog-lock-held (ADR 032).
    @contextmanager
    def catalog_transaction(self, *, immediate: bool = False) -> Iterator[None]:
        """Runs a group of catalog writes atomically.

        Re-entrant: nested calls join the outermost transaction. On error the
        whole group is rolled back and the exception re-raised. The catalog lock
        is held for the life of the transaction.

        ``immediate`` reserves SQLite's writer slot before the transaction reads,
        so a competing connection cannot make a stale decision from the same
        username state.
        """
        with self._catalog_lock:
            depth = getattr(self._local, "catalog_tx_depth", 0)
            self._local.catalog_tx_depth = depth + 1
            outermost = depth == 0
            original_isolation = self.catalog_conn.isolation_level
            try:
                if outermost:
                    self.catalog_conn.isolation_level = None
                    self.catalog_conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield
            except Exception:
                if outermost and self.catalog_conn.in_transaction:
                    self.catalog_conn.execute("ROLLBACK")
                raise
            else:
                if outermost:
                    self.catalog_conn.execute("COMMIT")
            finally:
                self._local.catalog_tx_depth = depth
                if outermost:
                    self.catalog_conn.isolation_level = original_isolation

    def _commit_catalog(self) -> None:
        """Commits a standalone catalog write, or defers to the active transaction."""
        if getattr(self._local, "catalog_tx_depth", 0) == 0:
            self.catalog_conn.commit()

    def _rollback_catalog(self) -> None:
        """Rolls back a standalone catalog write, or defers to the active transaction.

        Inside a ``catalog_transaction`` the outermost context manager owns the
        rollback, so a write helper that loses its own race must leave the
        transaction open for its caller to unwind.
        """
        if getattr(self._local, "catalog_tx_depth", 0) == 0:
            self.catalog_conn.rollback()
