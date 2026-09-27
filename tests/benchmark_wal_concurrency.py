import concurrent.futures
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import DatabaseManager


def simulate_player_session(user_id: int):
    db = DatabaseManager()
    username = f"stress_user_{user_id}"

    with db.open_ledger(username) as ledger:
        session_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        ledger.log_workout_session(session_id, now[:10], "Push", now, now, readiness_score=4)

        # Resolve valid exercise id from transparent catalog view
        cursor = ledger.conn.cursor()
        cursor.execute("SELECT id FROM exercises LIMIT 1")
        row = cursor.fetchone()
        ex_id = str(row[0]) if row else "ex_1"

        for s_idx in range(1, 16):
            ledger.log_workout_set(str(uuid.uuid4()), session_id, ex_id, s_idx, 100.0, 8, 8.5)

        history = ledger.get_last_performance(ex_id)
        assert len(history) == 15, f"Expected 15 sets for {username}, got {len(history)}"
    db.catalog_conn.close()
    return True


def run_concurrency():
    workers = 10
    print(f"⚡ Testing WAL Concurrency across {workers} simultaneous threads...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(simulate_player_session, i) for i in range(workers)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    assert all(results)
    print(f"✅ Successfully completed {workers} simultaneous user sessions without write contention or locks.")


if __name__ == "__main__":
    run_concurrency()
