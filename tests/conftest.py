"""Hermetic test environment.

Environment pins precede dotenv loading because ``load_dotenv()`` preserves
values that are already present in the process environment.
"""

import csv
import os
import re

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_API_BASE"] = ""
os.environ["LLM_EXTRA_BODY"] = ""
os.environ["LLM_ENABLE_THINKING"] = ""
# A developer's configured analytics key must never receive test traffic.
# ``load_dotenv()`` does not override these already-present environment keys.
os.environ["POSTHOG_API_KEY"] = ""

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


def _scripted_model_builder(_role):
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
    from database.database_manager import DatabaseManager

    handles: list = []
    original_init = DatabaseManager.__init__

    def _bind(self):
        self.ledger = self.open_ledger(self.default_ledger_id)
        handles.append(self.ledger)
        self.conn = self.ledger.conn
        self.ledger_conn = self.ledger.conn
        self._test_ledger_id = self.ledger.ledger_id

    def _switch_user(self, username):
        if self.ledger is not None:
            self.ledger.close()
        self.ledger = self.open_ledger(self._sanitize_username(username))
        handles.append(self.ledger)
        self.conn = self.ledger.conn
        self.ledger_conn = self.ledger.conn
        self._test_ledger_id = self.ledger.ledger_id
        return True

    def _create_ledger_schema(self):
        return None

    # ``__init__`` only (private, invisible to the public-surface snapshot), so no
    # public class attributes are added for tests to trip over.
    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        _bind(self)
        self.switch_user = _switch_user.__get__(self)
        self.create_ledger_schema = _create_ledger_schema.__get__(self)

    monkeypatch.setattr(DatabaseManager, "__init__", wrapped_init)
    yield
    for handle in handles:
        try:
            handle.close()
        except Exception:
            pass


@pytest.fixture
def fresh_store(tmp_path):
    """A fresh, isolated store bound to temporary registry + ledger paths (ADR 041).

    Copies the shipped exercise library so agent/program tests have a real
    exercise library. The autouse ``_test_ledger_facade`` fixture exposes an
    explicit ``db.ledger`` handle on it.
    """
    import shutil

    from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager

    catalog_path = tmp_path / "catalog.db"
    shutil.copyfile(DEFAULT_CATALOG_PATH, catalog_path)
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    try:
        yield db
    finally:
        db.catalog_conn.close()


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
