"""Guard Litestream's per-database interval policy."""

from pathlib import Path
import re


CONFIG = Path(__file__).resolve().parents[1] / "deploy" / "litestream.yml"


def _entry(config: str, path: str) -> str:
    match = re.search(
        rf"(?ms)^  - (?:path|dir): {re.escape(path)}\n(.*?)(?=^  - |\Z)",
        config,
    )
    assert match is not None, f"missing Litestream entry for {path}"
    return match.group(1)


def test_only_player_ledgers_override_litestream_intervals():
    config = CONFIG.read_text(encoding="utf-8")
    users = _entry(config, "/data/users")
    assert re.search(r"(?m)^    monitor-interval: 10s$", users)
    assert re.search(r"(?m)^      sync-interval: 10s$", users)
    assert re.search(r"(?m)^    watch: true$", users)

    for path in ("/data/catalog.db", "/data/deletions.db"):
        entry = _entry(config, path)
        assert not re.search(r"(?m)^    monitor-interval:", entry)
        assert not re.search(r"(?m)^      sync-interval:", entry)
