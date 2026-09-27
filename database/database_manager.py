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
DEFAULT_USERS_DIR = _DATA_ROOT / "users"
DEFAULT_BACKUPS_DIR = _DATA_ROOT / "backups"

from database.migration_manager import apply_lazy_migrations, prune_user_backups
from utils.logger import MyosLogger

from database.schema.definitions import SchemaMixin
from database.account_deletion import AccountDeletionMixin
from database.ledger.auth import LedgerAuthMixin
from database.registry.accounts import RegistryAccountsMixin
from database.registry.plans import RegistryPlansMixin
from database.registry.recovery import RegistryRecoveryMixin
from database.registry.coach_invites import RegistryCoachInvitesMixin
from database.registry.assignments import RegistryAssignmentsMixin
from database.registry.program_requests import RegistryProgramRequestsMixin
from database.registry.coach_alerts import RegistryCoachAlertsMixin
from database.registry.check_ins import RegistryCheckInsMixin
from database.registry.model_usage import RegistryModelUsageMixin
from database.exercise_library.lookup import ExerciseLookupMixin
from database.exercise_library.similarity import ExerciseSimilarityMixin
from database.exercise_library.seeding import ExerciseSeedingMixin
from database.ledger.training_program import LedgerTrainingProgramMixin
from database.ledger.workouts import LedgerWorkoutsMixin
from database.ledger.schedule import LedgerScheduleMixin
from database.ledger.profile import LedgerProfileMixin
from database.ledger.onboarding import LedgerOnboardingMixin
from database.ledger.chat import LedgerChatMixin
from database.ledger.debriefs import LedgerDebriefsMixin

logger = MyosLogger().get_logger(__name__)

# Re-exported so existing importers keep working after the module split (#78).
from database.shared import LedgerDeletedError
from database.shared import DEFAULT_CSV_PATH as DEFAULT_CSV_PATH  # noqa: F401  (re-export)
from database.shared import _normalize_exercise_name as _normalize_exercise_name  # noqa: F401


class DatabaseManager(
    SchemaMixin,
    AccountDeletionMixin,
    RegistryAccountsMixin,
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
    LedgerAuthMixin,
    LedgerTrainingProgramMixin,
    LedgerWorkoutsMixin,
    LedgerScheduleMixin,
    LedgerProfileMixin,
    LedgerOnboardingMixin,
    LedgerChatMixin,
    LedgerDebriefsMixin,
):
    EMBEDDING_DIM = 384

    def __init__(
        self,
        catalog_path=None,
        users_dir=None,
        backups_dir=None,
        active_user: str | None = None,
        deletions_path=None,
    ):
        if configured_data_root() is not None:
            root = validate_data_root()
        else:
            root = resolve_data_root()
        self.catalog_path = Path(catalog_path) if catalog_path is not None else root / "catalog.db"
        self.users_dir = Path(users_dir) if users_dir is not None else root / "users"
        self.backups_dir = Path(backups_dir) if backups_dir is not None else root / "backups"
        env_deletions = os.getenv("MAYOS_DELETIONS_DB", "").strip()
        if deletions_path is not None:
            self.deletions_path = Path(deletions_path)
        elif env_deletions:
            self.deletions_path = Path(env_deletions)
        else:
            self.deletions_path = self.catalog_path.parent / "deletions.db"
        self._default_user = self._sanitize_username(active_user) if active_user else "default"
        self._catalog_lock = threading.RLock()
        # The mounted-ledger state is per-instance (and per-thread within it), so
        # two stores never share an active user or connection.
        self._local = threading.local()

        os.makedirs(self.catalog_path.parent, exist_ok=True)
        os.makedirs(self.users_dir, exist_ok=True)
        os.makedirs(self.backups_dir, exist_ok=True)

        self.catalog_conn = sqlite3.connect(self.catalog_path, check_same_thread=False)
        self.catalog_conn.execute("PRAGMA foreign_keys = ON;")
        self.catalog_conn.execute("PRAGMA journal_mode = WAL;")
        self.catalog_conn.execute("PRAGMA busy_timeout = 5000;")
        self.catalog_conn.execute("PRAGMA synchronous = NORMAL;")
        self.catalog_conn.enable_load_extension(True)
        sqlite_vec.load(self.catalog_conn)
        self.catalog_conn.enable_load_extension(False)

        self.ensure_account_schema()

        self._initialize_deletions()

        self.switch_user(self._default_user)

        logger.info(f"DatabaseManager initialized with user ledger ({self.active_user}).")

    @property
    def active_user(self) -> str:
        return getattr(self._local, "active_user", getattr(self, "_default_user", "default"))

    @active_user.setter
    def active_user(self, val: str):
        self._local.active_user = val

    @property
    def user_conn(self) -> sqlite3.Connection | None:
        return getattr(self._local, "user_conn", None)

    @user_conn.setter
    def user_conn(self, val: sqlite3.Connection | None):
        self._local.user_conn = val

    @property
    def conn(self) -> sqlite3.Connection:
        c = self.user_conn
        if c is None:
            self.switch_user(self.active_user)
            c = self.user_conn
        if c is None:
            raise RuntimeError(f"No active database connection mounted for user '{self.active_user}'.")
        return c

    @staticmethod
    def _sanitize_username(username: str) -> str:
        clean = re.sub(r"[^\w\-]", "", str(username).strip().lower())
        return clean or "default"

    def switch_user(self, username: str) -> bool:
        sanitized = self._sanitize_username(username)
        if not sanitized:
            return False

        if self._ledger_is_deleted(sanitized):
            logger.warning(f"Refusing to mount deleted ledger '{sanitized}'.")
            raise LedgerDeletedError(f"Ledger '{sanitized}' belongs to a deleted account.")

        current_conn = self.user_conn
        if current_conn is not None and self.active_user == sanitized:
            return True

        if current_conn is not None:
            try:
                current_conn.commit()
                current_conn.close()
            except Exception as e:
                logger.warning(f"Error closing active connection for {self.active_user}: {e}")
            self.user_conn = None

        self.active_user = sanitized
        user_db_path = self.users_dir / f"{sanitized}.db"

        new_conn = sqlite3.connect(user_db_path, check_same_thread=False)
        new_conn.row_factory = sqlite3.Row
        new_conn.execute("PRAGMA foreign_keys = ON;")
        new_conn.execute("PRAGMA journal_mode = WAL;")
        new_conn.execute("PRAGMA busy_timeout = 5000;")
        new_conn.execute("PRAGMA synchronous = NORMAL;")

        escaped_path = str(self.catalog_path.resolve()).replace("'", "''")
        new_conn.execute(f"ATTACH DATABASE '{escaped_path}' AS catalog;")
        new_conn.execute("CREATE TEMP VIEW IF NOT EXISTS exercises AS SELECT * FROM catalog.exercises;")
        new_conn.execute(
            "CREATE TEMP VIEW IF NOT EXISTS exercise_secondary_muscles AS SELECT * FROM catalog.exercise_secondary_muscles;"
        )

        self.user_conn = new_conn

        apply_lazy_migrations(new_conn, sanitized, self.users_dir, self.backups_dir)

        self.create_user_schema()
        prune_user_backups(self.backups_dir / sanitized, max_rolling=3)
        return True

    def unmount_user(self) -> None:
        """Closes and clears this thread's mounted ledger connection.

        Background work (the alert sweep) shares ``asyncio``'s worker threads
        with request handlers; without this, a player's ledger connection would
        stay bound to that thread after the work finishes. Resets the thread to
        the default identity so the next ``bind_user``/``switch_user`` mounts
        cleanly.
        """
        current_conn = self.user_conn
        if current_conn is not None:
            try:
                current_conn.commit()
                current_conn.close()
            except Exception as e:
                logger.warning(f"Error closing active connection for {self.active_user}: {e}")
        self.user_conn = None
        self.active_user = getattr(self, "_default_user", "default")

    @contextmanager
    def catalog_locked(self) -> Iterator[sqlite3.Connection]:
        """Yields the shared catalog connection under the catalog lock.

        All direct catalog reads must go through this helper; the raw
        ``catalog_conn`` cursor is not thread-safe on its own.
        """
        with self._catalog_lock:
            yield self.catalog_conn

    def get_connection(self) -> sqlite3.Connection:
        return self.conn

    # Catalog transactions: re-entrant, catalog-lock-held (ADR 032).
    @contextmanager
    def catalog_transaction(self) -> Iterator[None]:
        """Runs a group of catalog writes atomically.

        Re-entrant: nested calls join the outermost transaction. On error the
        whole group is rolled back and the exception re-raised. The catalog lock
        is held for the life of the transaction.
        """
        with self._catalog_lock:
            depth = getattr(self._local, "catalog_tx_depth", 0)
            self._local.catalog_tx_depth = depth + 1
            outermost = depth == 0
            original_isolation = self.catalog_conn.isolation_level
            if outermost:
                self.catalog_conn.isolation_level = None
                self.catalog_conn.execute("BEGIN")
            try:
                yield
            except Exception:
                if outermost:
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

    # Ledger transactions: re-entrant, on the mounted ledger connection (ADR 020/033).
    @contextmanager
    def ledger_transaction(self) -> Iterator[None]:
        """Runs a group of ledger writes atomically.

        Re-entrant: nested calls join the outermost transaction. On error the
        whole group is rolled back and the exception re-raised.
        """
        conn = self.conn
        depth = getattr(self._local, "ledger_tx_depth", 0)
        self._local.ledger_tx_depth = depth + 1
        outermost = depth == 0
        original_isolation = conn.isolation_level
        if outermost:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            if outermost:
                conn.execute("ROLLBACK")
            raise
        else:
            if outermost:
                conn.execute("COMMIT")
        finally:
            self._local.ledger_tx_depth = depth
            if outermost:
                conn.isolation_level = original_isolation

    def _commit_ledger(self) -> None:
        """Commits a standalone ledger write, or defers to the active transaction."""
        if getattr(self._local, "ledger_tx_depth", 0) == 0:
            self.conn.commit()

    def commit_ledger(self) -> None:
        """Public seam for ledger writers outside this module (e.g. ``agent.progression_engine``)."""
        self._commit_ledger()
