"""Guard hourly R2 work and frequent local WAL handling."""

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


def test_all_replicas_sync_hourly_while_local_wal_monitoring_stays_frequent():
    config = CONFIG.read_text(encoding="utf-8")
    users = _entry(config, "/data/users")
    assert re.search(r"(?m)^    monitor-interval: 10s$", users)
    assert re.search(r"(?m)^    checkpoint-interval: 1m$", users)
    assert re.search(r"(?m)^    min-checkpoint-page-count: 1000$", users)
    assert re.search(r"(?m)^    truncate-page-n: 121359$", users)
    assert re.search(r"(?m)^      sync-interval: 1h$", users)
    assert re.search(r"(?m)^    watch: true$", users)

    for path in ("/data/catalog.db", "/data/deletions.db"):
        entry = _entry(config, path)
        assert re.search(r"(?m)^    monitor-interval: 1s$", entry)
        assert re.search(r"(?m)^    checkpoint-interval: 1m$", entry)
        assert re.search(r"(?m)^    min-checkpoint-page-count: 1000$", entry)
        assert re.search(r"(?m)^    truncate-page-n: 121359$", entry)
        assert re.search(r"(?m)^      sync-interval: 1h$", entry)


def test_periodic_remote_compaction_and_retention_are_daily_or_slower():
    config = CONFIG.read_text(encoding="utf-8")
    levels = re.search(r"(?ms)^levels:\n((?:  - interval: .+\n)+)", config)
    assert levels is not None
    assert re.findall(r"(?m)^  - interval: (.+)$", levels.group(1)) == ["24h"]
    assert re.search(r"(?m)^  interval: 24h$", config)
    assert re.search(r"(?m)^  retention: 24h$", config)
    assert re.search(r"(?m)^l0-retention: 5m$", config)
    assert re.search(r"(?m)^l0-retention-check-interval: 24h$", config)
    assert re.search(r"(?m)^  enabled: true$", config)
