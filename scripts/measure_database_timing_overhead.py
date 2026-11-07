"""Server-only benchmark: python -m scripts.measure_database_timing_overhead.

Run in the deployed environment, then record the printed medians in the PR.
This uses disposable, warmed in-memory indexed reads and the real recorder;
fetching is included equally in all three cases. It does not touch live data.
"""

import argparse
import platform
import sqlite3
from contextlib import closing
from statistics import median
from time import perf_counter

from database.sqlite_connection import connect_api_sqlite, set_query_recorder
from svc.monitoring.tiles.database import DatabaseProvider

SQL = "SELECT payload FROM records WHERE id = ?"


def _read_loop(connection, iterations: int) -> float:
    started = perf_counter()
    for index in range(iterations):
        connection.execute(SQL, (index % 1000,)).fetchone()
    return (perf_counter() - started) * 1_000_000 / iterations


def measure(iterations: int, repeats: int) -> None:
    provider = DatabaseProvider()
    samples: dict[str, list[float]] = {"native": [], "hook_disabled": [], "hook_enabled": []}
    with closing(sqlite3.connect(":memory:", check_same_thread=False)) as native, closing(connect_api_sqlite(":memory:")) as timed:
        for connection in (native, timed):
            connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, payload TEXT)")
            connection.executemany("INSERT INTO records VALUES (?, ?)", [(index, "example") for index in range(1000)])
            connection.commit()
        for repeat in range(repeats):
            # Rotate order to reduce systematic bias from clock/thermal changes.
            cases = [("native", native, None), ("hook_disabled", timed, None), ("hook_enabled", timed, provider.record)]
            offset = repeat % len(cases)
            for label, connection, recorder in cases[offset:] + cases[:offset]:
                set_query_recorder(recorder)
                _read_loop(connection, 1000)
                samples[label].append(_read_loop(connection, iterations))
    set_query_recorder(None)
    medians = {label: median(durations) for label, durations in samples.items()}
    print(f"{iterations:,} indexed reads/repeat; {repeats} repeats; median microseconds/read (includes fetchone)")
    for label, duration in medians.items():
        overhead = duration - medians["native"]
        print(f"{label}: {duration:.3f} us; versus native: {overhead:+.3f} us ({overhead / medians['native']:+.1%})")
    print(f"Recorder increment over disabled hook: {medians['hook_enabled'] - medians['hook_disabled']:+.3f} us/read")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100000)
    parser.add_argument("--repeats", type=int, default=9)
    args = parser.parse_args()
    if args.iterations < 1 or args.repeats < 1:
        parser.error("iterations and repeats must be positive")
    print(f"Python {platform.python_version()}; SQLite {sqlite3.sqlite_version}; {platform.platform()}")
    try:
        measure(args.iterations, args.repeats)
    finally:
        set_query_recorder(None)


if __name__ == "__main__":
    main()
