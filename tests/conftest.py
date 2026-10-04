"""Hermetic test environment.

``agent/*`` modules call ``load_dotenv()`` at import time, which injects any
``.env`` keys not already present into ``os.environ``. If a developer keeps
cloud settings (``LLM_BACKEND=openai`` / ``LLM_API_KEY``) in their ``.env``,
every local-path unit test would silently take the cloud branch.

Declaring the backend pins here — at conftest import, before any test module is
collected — keeps the suite deterministic. ``load_dotenv()`` does not override
existing keys, and empty strings count as existing, so these neutral values
survive the agent-module imports. Cloud tests override them explicitly with
``monkeypatch.setenv`` and restore to these values on teardown.
"""

import os
import re

import pytest

os.environ["LLM_BACKEND"] = "local"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_API_BASE"] = ""
os.environ["LLM_EXTRA_BODY"] = ""
os.environ["LLM_ENABLE_THINKING"] = ""

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
