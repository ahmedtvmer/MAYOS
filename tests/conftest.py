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
def _isolate_active_store():
    """Starts every test with no ambient store, so tests cannot leak stores into each other.

    Tests that exercise agent graphs or metering call ``database.store.set_store``
    (directly or via :func:`service._base.bind_user`) with their own fresh store;
    whatever they set is discarded here so run order cannot change the outcome.
    """
    from database.store import reset_store, set_store

    token = set_store(None)
    try:
        yield
    finally:
        reset_store(token)


@pytest.fixture
def fresh_store(tmp_path):
    """A fresh, isolated store bound to temporary registry + ledger paths (ADR 041).

    Copies the shipped exercise catalog so agent/program tests have a real
    exercise library, and publishes the store as the active one for the test.
    """
    import shutil

    from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager
    from database.store import set_store

    catalog_path = tmp_path / "catalog.db"
    shutil.copyfile(DEFAULT_CATALOG_PATH, catalog_path)
    db = DatabaseManager(
        catalog_path=catalog_path,
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    set_store(db)
    try:
        yield db
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()
