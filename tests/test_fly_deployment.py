"""Fly.io trial storage contract tests.

Behavioral FastAPI tests at the agreed seam: a temporary directory stands in for
the mounted volume and a real SQLite catalog/ledger is created on it. Register
and login touch only SQLite, so no LLM or external service is involved.

Also pins the build context of the Fly image (issue #161): the catalog
pictures that ``GET /media`` serves ship with it, and nothing else under
``data/`` does.
"""

import os
import re
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.storage import StorageNotReady, storage_status, validate_data_root
from svc.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent


def _start_fresh_db(monkeypatch):
    """Reset the process-wide LLM cache; each test builds its own fresh store."""
    from utils import model_downloader as md

    md._llm_instance = None
    md._judge_llm_instance = None
    md._coach_llm_instance = None


@pytest.fixture
def clean_db(monkeypatch):
    _start_fresh_db(monkeypatch)
    yield


def _prepare_env(monkeypatch, data_dir: Path):
    from svc.rate_limit import limiter

    limiter._storage.reset()
    monkeypatch.setenv("MAYOS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("MAYOS_REQUIRE_PERSISTENT_DATA", raising=False)
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.delenv("SKIP_LLM_LOAD", raising=False)


def test_missing_mount_rejects_readiness_and_writes(clean_db, monkeypatch, tmp_path):
    missing = tmp_path / "not-mounted"
    _prepare_env(monkeypatch, missing)

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        response = client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})

    # A valid-looking request must fail, not silently provision ephemeral state.
    assert response.status_code >= 500
    assert not missing.exists()


def test_mounted_root_persists_account_across_restart(clean_db, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _prepare_env(monkeypatch, data_dir)

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        created = client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert created.status_code == 201
    assert (data_dir / "catalog.db").is_file()
    assert (data_dir / "users" / "alice.db").is_file()

    # Simulate an always-on Machine restart: boot a fresh app against the same
    # mounted root. The account must survive.
    _start_fresh_db(monkeypatch)
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        duplicate = client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
        login = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert duplicate.status_code == 409
    assert login.status_code == 200


def test_readyz_flips_when_data_root_becomes_unwritable(clean_db, monkeypatch, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _prepare_env(monkeypatch, data_dir)

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert client.get("/readyz").status_code == 200
        data_dir.chmod(0o500)
        try:
            response = client.get("/readyz")
        finally:
            data_dir.chmod(0o700)

    assert response.status_code == 503
    assert response.json()["details"]["storage"] is False
    assert response.json()["details"]["storage_detail"] == "data-dir-not-ready"


def _require_persistent_env(monkeypatch, data_dir: Path):
    monkeypatch.setenv("MAYOS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MAYOS_REQUIRE_PERSISTENT_DATA", "true")


def test_volume_snapshots_disabled_on_every_mount():
    """ADR 015/044: Fly scheduled snapshots stay off; backups are owned by #41."""
    fly_toml = Path(__file__).resolve().parent.parent / "fly.toml"
    config = tomllib.loads(fly_toml.read_text())
    mounts = config.get("mounts", [])
    assert mounts, "fly.toml declares no [[mounts]]"
    for mount in mounts:
        assert mount.get("scheduled_snapshots") is False, f"mount {mount.get('source')} has snapshots enabled"


def test_required_persistent_root_accepts_real_mount(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _require_persistent_env(monkeypatch, data_dir)
    monkeypatch.setattr(os.path, "ismount", lambda path: True)

    assert validate_data_root() == data_dir
    assert storage_status() == (True, "ok")


def test_required_persistent_root_fails_closed_without_mount(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _require_persistent_env(monkeypatch, data_dir)
    monkeypatch.setattr(os.path, "ismount", lambda path: False)

    with pytest.raises(StorageNotReady):
        validate_data_root()
    assert storage_status() == (False, "data-dir-not-ready")


# --------------------------------------------------------------------------
# Build context: the catalog pictures and GIFs ship, the rest of data/ stays
# out (#161, #53)
# --------------------------------------------------------------------------


def _glob_to_regex(pattern: str) -> str:
    """Go `filepath.Match` for a context-relative path: `*`/`?` never cross
    a separator, `**` does."""
    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        char = pattern[index]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    return "".join(out)


def _dockerignore_rules(path: Path = REPO_ROOT / ".dockerignore") -> list[tuple[bool, re.Pattern]]:
    """`.dockerignore` as (negated, compiled pattern) pairs, in file order.

    Mirrors how the Docker CLI resolves the build context: rules are matched
    against context-relative paths and the last matching rule wins — modern
    Docker can re-include a path under an excluded parent when a later `!`
    rule matches it (`!data/videos/**`), while a subtree no rule re-includes
    stays out.
    """
    rules: list[tuple[bool, re.Pattern]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        line = line.lstrip("/")
        if line.endswith("/"):
            # `dir/` covers the directory itself and everything inside it.
            compiled = re.escape(line.rstrip("/")) + r"(?:/.*)?"
        else:
            compiled = _glob_to_regex(line.rstrip("/"))
        rules.append((negated, re.compile(compiled + r"\Z")))
    return rules


def _in_build_context(path: str, rules: list[tuple[bool, re.Pattern]]) -> bool:
    """True when `fly deploy` would send `path` to `docker build`.

    Walks every prefix from the context root down to the path itself, last
    matching rule wins across the whole walk: a later `!` rule re-includes
    even under an excluded parent, and a prefix no rule re-includes keeps an
    earlier exclusion.
    """
    parts = path.split("/")
    excluded = False
    for depth in range(1, len(parts) + 1):
        prefix = "/".join(parts[:depth])
        for negated, pattern in rules:
            if pattern.match(prefix):
                excluded = not negated
    return not excluded


def test_build_context_ships_catalog_media_and_nothing_else_from_data():
    """`data/images` and `data/videos` are in the Fly build context; the rest
    of `data/` is not.

    The app loads `GET /media/<image_path>` and `GET /media/<gif_path>` (#161,
    #53), and the route resolves those paths under `/app/data`, so the cards'
    pictures and the exercise-detail GIFs have to be in the image while the
    databases and the raw dump stay out.
    """
    rules = _dockerignore_rules()

    assert _in_build_context("data/images/0001-2gPfomN.jpg", rules)
    assert _in_build_context("data/images/nested/one.jpg", rules)
    assert _in_build_context("data/videos/0001-2gPfomN.gif", rules)
    assert _in_build_context("data/processed_exercises.csv", rules)

    assert not _in_build_context("data/catalog.db", rules)
    assert not _in_build_context("data/exercises.json", rules)
    assert not _in_build_context("data/deletions.db", rules)


def test_build_context_keeps_the_owner_exclusions():
    """docs (beyond the privacy policy), plans, agent tooling and wrangler
    state stay out of the build context, as before issue #161."""
    rules = _dockerignore_rules()

    assert not _in_build_context("docs/DEPLOYMENT.md", rules)
    assert _in_build_context("docs/PRIVACY_POLICY.md", rules)
    assert not _in_build_context("plans/MAYOS_LOGGER_Redesign.md", rules)
    assert not _in_build_context(".claude/worktrees/issue-161/app.py", rules)
    assert not _in_build_context(".wrangler/state.json", rules)
    assert not _in_build_context("mobile/lib/main.dart", rules)
    assert not _in_build_context(".venv/lib/python3.12/site-packages/x.py", rules)


def test_dockerfile_fly_copies_catalog_media_where_media_looks():
    """`Dockerfile.fly` puts the media at `/app/data/{images,videos}`, the
    directories `svc/routers/media.py` resolves `image_path`/`gif_path`
    against (BASE_DIR/data)."""
    dockerfile = (REPO_ROOT / "Dockerfile.fly").read_text(encoding="utf-8")

    assert re.search(r"^COPY data/images /app/data/images$", dockerfile, re.M)
    assert re.search(r"^COPY data/videos /app/data/videos$", dockerfile, re.M)
    # `COPY . .` is filtered by .dockerignore, so the re-included pictures
    # reach the same directory from the context as well.
    assert re.search(r"^COPY \. \.$", dockerfile, re.M)
    assert re.search(r"^COPY data/processed_exercises\.csv ", dockerfile, re.M)


def test_real_checkout_catalog_media_are_in_the_context():
    """In a checkout that has the (gitignored) media, every one of the
    pictures and GIFs reaches the build context — the case the owner actually
    deploys from."""
    rules = _dockerignore_rules()
    media = [
        entry
        for directory in (REPO_ROOT / "data" / "images", REPO_ROOT / "data" / "videos")
        if directory.is_dir()
        for entry in directory.rglob("*")
        if entry.is_file()
    ]
    if not media:
        pytest.skip("data/images and data/videos are not present in this checkout")

    files = media
    assert files
    for file in files:
        relative = file.relative_to(REPO_ROOT).as_posix()
        assert _in_build_context(relative, rules), relative
