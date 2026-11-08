"""Server-only timings: python -m scripts.measure_register_intake --samples 5.

Uses the real API via HTTPX ASGITransport with a disposable catalog and fresh ledgers.
No inference, external analytics, email, or background backup jobs are started.
Password hashing, per-mount migrations, schema setup and snapshots stay real.
Use --directory /data to put disposable files on the server's data filesystem.
Copy this script to the baseline revision too, and run both on the same server.
Totals include response serialization and handle cleanup; phase timings overlap
(schema/migrations/pruning are inside ledger_open). Startup/imports are excluded.
This is a sequential local baseline, not a staging load or replication benchmark.
"""

import argparse
import asyncio
import logging
import os
import platform
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from functools import wraps
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch


ANSWERS = (
    ("age", 29),
    ("current_goal", "build glutes and legs"),
    ("long_term_goal", "stronger and more muscular"),
    ("injuries_or_limitations", "None"),
)


def _timed_call(phases, label, call):
    @wraps(call)
    def measured(*args, **kwargs):
        started = perf_counter()
        try:
            return call(*args, **kwargs)
        finally:
            phases[label].append((perf_counter() - started) * 1000)

    return measured


@contextmanager
def _phase_timings(db):
    from database import database_manager, migration_manager
    from service import auth, intake

    phases = defaultdict(list)
    targets = (
        (auth, "hash_password", "bcrypt"),
        (db, "open_ledger", "ledger_open"),
        (database_manager, "apply_lazy_migrations", "migrations"),
        (db, "_create_ledger_schema_on", "schema_ensure"),
        (database_manager, "prune_ledger_backups", "backup_pruning"),
        (migration_manager, "create_atomic_backup", "snapshot"),
        (intake, "save_answer", "save_answer_and_view"),
    )
    with ExitStack() as patches:
        for owner, name, label in targets:
            patches.enter_context(patch.object(owner, name, _timed_call(phases, label, getattr(owner, name))))
        yield phases


async def _request_sample(phases, samples, send):
    phases.clear()
    started = perf_counter()
    response = await send()
    elapsed = (perf_counter() - started) * 1000
    response.raise_for_status()
    samples.append({"total": elapsed, **{label: sum(durations) for label, durations in phases.items()}})
    return response


async def _collect_samples(client, phases, args):
    registration_samples, answer_samples = [], []
    for index in range(args.samples):
        registered = await _request_sample(phases, registration_samples, lambda: client.post(
            "/auth/register", json={"trainee_id": f"perf-register-{index}", "password": "timing-only-password-123"},
        ))
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        disclosure = await client.post("/onboarding/intake/disclosure", headers=headers)
        disclosure.raise_for_status()
        for answer_index in range(args.answers):
            field, answer = ANSWERS[answer_index % len(ANSWERS)]
            await _request_sample(phases, answer_samples, lambda: client.put(
                f"/onboarding/intake/answers/{field}", headers=headers, json={"value": answer},
            ))
    return registration_samples, answer_samples


def _print_samples(label, samples):
    print(f"\n{label}: {len(samples)} requests; milliseconds")
    print("phase                         mean      median         max")
    for phase in dict.fromkeys(phase for sample in samples for phase in sample):
        durations = [sample.get(phase, 0.0) for sample in samples]
        print(f"{phase:26} {mean(durations):10.3f} {median(durations):11.3f} {max(durations):11.3f}")
    print(f"First request total: {samples[0]['total']:.3f} ms")


async def _measure(root, args):
    import httpx

    from database.database_manager import DatabaseManager
    from svc.app import create_app
    from svc.rate_limit import limiter

    logging.getLogger("mayos").setLevel(logging.ERROR)
    db = DatabaseManager(catalog_path=root / "catalog.db", ledgers_dir=root / "users",
                         backups_dir=root / "backups", deletions_path=root / "deletions.db")
    app = create_app()
    app.state.db = db
    # Only this disposable app is measured; repeated registrations must not hit
    # the production anti-abuse budget and turn timings into 429 measurements.
    limiter.enabled = False
    try:
        # ASGITransport does not enter lifespan, so production sweep, monitoring
        # and backup tasks stay off. All samples share one event loop and pool.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            with _phase_timings(db) as phases:
                registration_samples, answer_samples = await _collect_samples(client, phases, args)
        _print_samples("POST /auth/register", registration_samples)
        _print_samples("PUT /onboarding/intake/answers/{field}", answer_samples)
    finally:
        db.deletions_conn.close()
        db.catalog_conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5, help="fresh registrations")
    parser.add_argument("--answers", type=int, default=12, help="answer saves per new account")
    parser.add_argument("--directory", type=Path, help="existing parent directory for disposable databases")
    args = parser.parse_args()
    if args.samples < 1 or args.answers < 1:
        parser.error("samples and answers must be positive")
    print(f"Python {platform.python_version()}; {platform.platform()}")
    with TemporaryDirectory(prefix="perf-register-", dir=args.directory) as directory:
        root = Path(directory)
        with patch.dict(os.environ, {
            "MAYOS_DATA_DIR": str(root), "MAYOS_DELETIONS_DB": str(root / "deletions.db"),
            "MAYOS_REQUIRE_PERSISTENT_DATA": "false", "SKIP_LLM_LOAD": "true", "TESTING": "1",
            "JWT_SECRET": "disposable-register-intake-timing-secret", "SENTRY_DSN": "", "POSTHOG_API_KEY": "",
            "SMTP_HOST": "", "DISCORD_ALERT_WEBHOOK_URL": "", "MIN_ANDROID_BUILD": "0",
        }):
            print(f"Disposable data: {root}")
            asyncio.run(_measure(root, args))


if __name__ == "__main__":
    main()
