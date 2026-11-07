"""Hermetic test environment.

Environment pins precede dotenv loading because ``load_dotenv()`` preserves
values that are already present in the process environment.
"""

import csv
import os
import re
from contextlib import ExitStack
from functools import wraps
from pathlib import Path

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_API_BASE"] = ""
os.environ["LLM_EXTRA_BODY"] = ""
os.environ["LLM_ENABLE_THINKING"] = ""
# A developer's configured analytics key must never receive test traffic.
# ``load_dotenv()`` does not override these already-present environment keys.
os.environ["POSTHOG_API_KEY"] = ""

# Tests must not post Sentry alerts using a developer/server webhook from .env.
os.environ["DISCORD_ALERT_WEBHOOK_URL"] = ""

# Same for outbound email: a developer `.env` with real SMTP settings must not
# make tests send mail. ``service/email_sender._deliver`` treats an empty
# SMTP_HOST as its console backend, so pinning it empty makes delivery hermetic.
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_PORT"] = ""
os.environ["SMTP_USE_TLS"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["SMTP_FROM"] = ""
os.environ["OWNER_ALERT_EMAIL"] = ""

from utils import model_downloader as _model_downloader
from tests.fakes.chat_model import ScriptedChatModel

_REAL_CLOUD_MODEL_BUILDER = _model_downloader._build_cloud_llm
_COLLECTION_CHAT_MODEL = ScriptedChatModel(default_turn="Use controlled reps.")
_ACTIVE_TEST_CHAT_MODEL = _COLLECTION_CHAT_MODEL


def _scripted_model_builder(_role, **_settings):
    return _ACTIVE_TEST_CHAT_MODEL


# Collection imports can call ``get_llm`` before pytest fixtures run; keeping
# this one builder installed makes those imports use a network-free model.
_model_downloader._build_cloud_llm = _scripted_model_builder


@pytest.fixture
def scripted_chat_model():
    # Unrelated legacy paths get an explicit answer; tests that need exhaustion
    # failures can construct/reset the fake without a default_turn.
    return ScriptedChatModel(default_turn="Use controlled reps.")


@pytest.fixture(autouse=True)
def _install_scripted_chat_model(scripted_chat_model):
    """Makes default player, judge, and coach calls hermetic in every test."""
    global _ACTIVE_TEST_CHAT_MODEL
    from utils import model_downloader

    _ACTIVE_TEST_CHAT_MODEL = scripted_chat_model
    model_downloader._llm_instance = None
    model_downloader._judge_llm_instance = None
    model_downloader._coach_llm_instance = None
    model_downloader._coach_import_llm_instance = None
    return scripted_chat_model


@pytest.fixture
def hosted_model_builder(monkeypatch):
    """Restores the real hosted builder for factory configuration tests."""
    from utils import model_downloader

    monkeypatch.setattr(model_downloader, "_build_cloud_llm", _REAL_CLOUD_MODEL_BUILDER)
    return _REAL_CLOUD_MODEL_BUILDER


@pytest.fixture(autouse=True)
def recording_analytics():
    """Installs the strict analytics contract sink for every test."""
    from service.analytics import (
        RecordingAnalyticsSink,
        override_analytics_preference_reader,
        set_sink,
    )

    sink = RecordingAnalyticsSink()
    # Accounts allow analytics unless a test installs the registry preference.
    override_analytics_preference_reader(lambda _account_id: True)
    set_sink(sink)
    try:
        yield sink
    finally:
        override_analytics_preference_reader(None)
        set_sink(None)


@pytest.fixture(autouse=True)
def _test_ledger_facade(monkeypatch):
    """Test-only convenience: one explicit ``db.ledger`` handle per store.

    Production ``DatabaseManager`` has no mounted ledger: every caller opens a
    :class:`~database.ledger.handle.TrainingLedger` explicitly (ADR 041). Tests
    that predate the split construct a store and address its ledger directly;
    this fixture opens (and closes) the handle those tests name as ``db.ledger``
    and keeps ``switch_user`` as "reopen ``db.ledger`` for this id". The ledger
    operations themselves are still called explicitly on the handle object.
    """
    from database import account_deletion, database_manager
    from database.database_manager import DatabaseManager

    handles: list = []
    connections: list = []
    original_init = DatabaseManager.__init__
    original_open_ledger = DatabaseManager.open_ledger
    original_connect = database_manager.connect_api_sqlite

    def tracked_connect(database, **kwargs):
        connection = original_connect(database, **kwargs)
        # Track at open time, including ledger initialization that raises
        # before a TrainingLedger is returned to its caller.
        connections.append(connection)
        return connection

    def tracked_open_ledger(self, *args, **kwargs):
        handle = original_open_ledger(self, *args, **kwargs)
        handles.append(handle)
        return handle

    def _bind(self):
        self.ledger = self.open_ledger(self.default_ledger_id)
        self.conn = self.ledger.conn
        self.ledger_conn = self.ledger.conn
        self._test_ledger_id = self.ledger.ledger_id

    def _switch_user(self, username):
        if self.ledger is not None:
            self.ledger.close()
        self.ledger = self.open_ledger(self._sanitize_username(username))
        self.conn = self.ledger.conn
        self.ledger_conn = self.ledger.conn
        self._test_ledger_id = self.ledger.ledger_id
        return True

    def _create_ledger_schema(self):
        return None

    # Convenience methods stay on instances. The open_ledger wrapper retains
    # the production signature for the public-surface snapshot.
    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        _bind(self)
        self.switch_user = _switch_user.__get__(self)
        self.create_ledger_schema = _create_ledger_schema.__get__(self)

    monkeypatch.setattr(DatabaseManager, "__init__", wrapped_init)
    monkeypatch.setattr(DatabaseManager, "open_ledger", wraps(original_open_ledger)(tracked_open_ledger))
    monkeypatch.setattr(database_manager, "connect_api_sqlite", tracked_connect)
    monkeypatch.setattr(account_deletion, "connect_api_sqlite", tracked_connect)
    try:
        yield
    finally:
        # ExitStack attempts every close even if one resource raises; teardown
        # failures remain visible instead of being swallowed.
        with ExitStack() as cleanup:
            for connection in connections:
                cleanup.callback(connection.close)
            for handle in handles:
                cleanup.callback(handle.close)


@pytest.fixture(scope="session")
def synthetic_exercise_seed(tmp_path_factory):
    from tests.catalog import write_exercise_seed

    return write_exercise_seed(tmp_path_factory.mktemp("exercise-seed"))


@pytest.fixture(scope="session")
def synthetic_exercise_curation(tmp_path_factory):
    from tests.catalog import write_exercise_curation

    return write_exercise_curation(tmp_path_factory.mktemp("exercise-curation"))


@pytest.fixture(autouse=True)
def _test_seed_defaults(monkeypatch, synthetic_exercise_seed):
    """Default seeding never reads developer data; explicit test paths win."""
    from database.exercise_library.seeding import ExerciseSeedingMixin
    from tests.catalog import FIXTURES

    original = ExerciseSeedingMixin.initialize_and_seed

    @wraps(original)
    def initialize(self, *args, **kwargs):
        if not args and "csv_path" not in kwargs:
            kwargs["csv_path"] = synthetic_exercise_seed
        if len(args) < 2 and "curation_path" not in kwargs:
            kwargs["curation_path"] = self.curation_path
        if kwargs.get("food_path") is None:
            kwargs["food_path"] = FIXTURES / "smoke_food_library.csv"
        if kwargs.get("portion_path") is None:
            kwargs["portion_path"] = FIXTURES / "smoke_food_portions.csv"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ExerciseSeedingMixin, "initialize_and_seed", initialize)


@pytest.fixture(scope="session")
def seeded_catalog(tmp_path_factory):
    """Build once from tracked seeds; copies contain no accounts or ledgers."""
    from tests.catalog import close_catalog_store, create_catalog_store

    store = create_catalog_store(tmp_path_factory.mktemp("catalog-seed"))
    try:
        # Copying an SQLite WAL database before checkpointing loses seed rows.
        checkpoint = store.catalog_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        assert checkpoint[0] == 0, "Synthetic catalog checkpoint was blocked"
        path = store.catalog_path
    finally:
        close_catalog_store(store)
    return path


@pytest.fixture
def fresh_store(tmp_path, seeded_catalog, synthetic_exercise_curation):
    """A fresh, isolated store bound to temporary registry + ledger paths (ADR 041).

    Copies a catalog built from tracked synthetic seeds. The autouse
    ``_test_ledger_facade`` fixture exposes an
    explicit ``db.ledger`` handle on it.
    """
    import shutil

    from database.database_manager import DatabaseManager

    catalog_path = tmp_path / "catalog.db"
    shutil.copyfile(seeded_catalog, catalog_path)
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        curation_path=synthetic_exercise_curation,
    )
    try:
        yield db
    finally:
        db.catalog_conn.close()


@pytest.fixture
def editable_catalog_rows(fresh_store):
    """Visible exercises allowed by the default Commercial gym profile."""
    from database.exercise_library.schema import exercise_library_visible_sql
    from utils.equipment_access import COMMERCIAL_GYM, equipment_access_sql

    with fresh_store.catalog_locked() as conn:
        return conn.execute(
            "SELECT e.id, e.name FROM exercises e WHERE "
            + exercise_library_visible_sql("e.id")
            + " AND " + equipment_access_sql(COMMERCIAL_GYM, "e.equipment")
            + " ORDER BY e.id LIMIT 3"
        ).fetchall()


@pytest.fixture
def real_library_store(tmp_path):
    """Optional full-library contracts whose names/relationships are not tracked."""
    from database.database_manager import DatabaseManager
    from tests.catalog import ROOT, close_catalog_store, seed_catalog

    real_exercises = ROOT / "data" / "processed_exercises.csv"
    if not real_exercises.is_file():
        pytest.skip("Full-library contract requires optional licensed data/processed_exercises.csv; tracked sources do not supply its complete names/relationships")
    store = DatabaseManager(
        catalog_path=tmp_path / "real-library.db",
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    try:
        seed_catalog(store, csv_path=real_exercises)
        yield store
    finally:
        close_catalog_store(store)


@pytest.fixture
def git_checkout():
    """Git-index assertions cannot run in a production image/source archive."""
    import shutil

    root = Path(__file__).resolve().parents[1]
    if shutil.which("git") is None:
        pytest.skip("Git-index check requires git; the production API image does not include it")
    if not (root / ".git").exists():
        pytest.skip("Git-index check requires .git metadata; source archives/images omit it")
    return root


@pytest.fixture
def seed_exercise_curation(tmp_path, monkeypatch):
    """Apply a small curation CSV through the public Exercise library seeder."""
    from database.exercise_library import embeddings
    from database.schema.definitions import EMBEDDING_DIM

    class LocalEmbeddingStub:
        def embed_query(self, _text):
            return [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    monkeypatch.setattr(embeddings, "_load_embedding_model", lambda: LocalEmbeddingStub())

    def apply(store, records):
        from tests.catalog import invented_exercise_curation

        # These define the synthetic support catalog, not the real rows a test
        # is curating. Keep them eligible while replacing real-row curation.
        support = {
            row["id"]: {key: value for key, value in row.items() if key != "id"}
            for row in invented_exercise_curation()
            if store.get_exercise_library_entry(row["id"]) is not None
        }
        records = {**support, **records}
        seed_path = tmp_path / "curation-seed.csv"
        with seed_path.open("w", newline="", encoding="utf-8") as seed_file:
            writer = csv.writer(seed_file)
            writer.writerow(
                ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
            )

        curation_path = tmp_path / "exercise-curation.csv"
        curation_columns = [
            "id",
            "source_name",
            "display_name",
            "aliases",
            "primary_action",
            "secondary_actions",
            "primary_muscle",
            "load_type",
            "hidden",
            "duplicate_of",
        ]
        with curation_path.open("w", newline="", encoding="utf-8") as curation_file:
            writer = csv.writer(curation_file)
            writer.writerow(curation_columns)
            for exercise_id, fields in records.items():
                entry = store.get_exercise_library_entry(exercise_id)
                assert entry is not None, f"Unknown Exercise library id {exercise_id!r}"
                row = {"id": exercise_id, "source_name": entry["name"]}
                row.update(fields)
                for column in curation_columns:
                    field_value = row.get(column, "")
                    if column in {"aliases", "secondary_actions"} and isinstance(
                        field_value, (list, tuple)
                    ):
                        field_value = "|".join(field_value)
                    elif column == "hidden" and isinstance(field_value, bool):
                        field_value = str(field_value).lower()
                    row[column] = field_value
                writer.writerow([row[column] for column in curation_columns])

        store.initialize_and_seed(seed_path, curation_path)

    return apply


@pytest.fixture
def mark_recovery_email_verified():
    def mark(db, account_id):
        with db.catalog_locked() as conn:
            conn.execute(
                "UPDATE trainee_emails SET verified = 1 WHERE trainee_id = ?",
                (account_id,),
            )
            conn.commit()

    return mark


@pytest.fixture
def verify_recovery_email():
    def verify(client, token, monkeypatch):
        from service import email_sender

        codes = []

        def capture(_to_email, _subject, body, *, delivery):
            match = re.search(r"(?<!\d)\d{6}(?!\d)", body)
            assert match is not None
            codes.append(match.group())
            return True

        monkeypatch.setattr(email_sender, "_deliver", capture)
        headers = {"Authorization": f"Bearer {token}"}
        sent = client.post("/auth/email/verification-code", headers=headers)
        assert sent.status_code == 200, sent.text
        verified = client.post(
            "/auth/email/verify", json={"code": codes[0]}, headers=headers
        )
        assert verified.status_code == 200, verified.text

    return verify
