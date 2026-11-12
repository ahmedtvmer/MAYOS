"""Catalog-side Food swap queue, pinned to an Assignment and Nutrition version."""

import json


DDL = (
    """CREATE TABLE IF NOT EXISTS food_swap_requests (
        request_id TEXT PRIMARY KEY,
        assignment_id TEXT NOT NULL,
        coach_account_id TEXT NOT NULL,
        player_account_id TEXT NOT NULL,
        target_json TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending', 'applied', 'declined', 'closed')),
        response TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        resolved_by TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS food_swap_requests_assignment ON food_swap_requests(assignment_id, status)",
    "CREATE INDEX IF NOT EXISTS food_swap_requests_player ON food_swap_requests(player_account_id)",
    """CREATE TRIGGER IF NOT EXISTS close_assignment_food_swap_requests
        AFTER UPDATE OF status ON assignments
        WHEN NEW.status != 'active'
        BEGIN
            UPDATE food_swap_requests SET status='closed', resolved_at=NEW.ended_at,
                resolved_by=NEW.ended_by
            WHERE assignment_id=NEW.assignment_id AND status='pending';
        END""",
    """CREATE TRIGGER IF NOT EXISTS delete_account_food_swap_requests
        BEFORE DELETE ON accounts BEGIN
            DELETE FROM food_swap_requests
            WHERE player_account_id=OLD.account_id OR coach_account_id=OLD.account_id;
        END""",
    """CREATE TRIGGER IF NOT EXISTS clear_deleted_account_food_swap_requests
        AFTER UPDATE OF status ON accounts WHEN NEW.status='deleted' BEGIN
            DELETE FROM food_swap_requests
            WHERE player_account_id=NEW.account_id OR coach_account_id=NEW.account_id;
        END""",
)


def ensure_schema(connection):
    for statement in DDL:
        connection.execute(statement)


def _present(cursor):
    columns = [column[0] for column in cursor.description]
    requests = []
    for row in cursor.fetchall():
        request_record = dict(zip(columns, row))
        request_record["food_swap"] = json.loads(request_record.pop("target_json"))
        requests.append({**request_record, "kind": "food_swap", "program_version": None})
    return requests


def for_player(db, player_id):
    db.ensure_account_schema()
    with db.catalog_locked() as connection:
        return _present(connection.execute(
            "SELECT * FROM food_swap_requests WHERE player_account_id=? ORDER BY created_at DESC",
            (player_id,),
        ))


def for_coach(db, coach_id, assignment_id=None):
    db.ensure_account_schema()
    with db.catalog_locked() as connection:
        return _present(connection.execute(
            "SELECT r.*, acc.username AS player_username FROM food_swap_requests r "
            "JOIN assignments a ON a.assignment_id=r.assignment_id "
            "JOIN accounts acc ON acc.account_id=r.player_account_id "
            "WHERE a.coach_account_id=? AND a.status='active' "
            "AND (? IS NULL OR a.assignment_id=?) ORDER BY r.created_at DESC",
            (coach_id, assignment_id, assignment_id),
        ))


def get(db, coach_id, assignment_id, request_id):
    with db.catalog_locked() as connection:
        rows = _present(connection.execute(
            "SELECT * FROM food_swap_requests WHERE request_id=? AND coach_account_id=? AND assignment_id=?",
            (request_id, coach_id, assignment_id),
        ))
    return rows[0] if rows else None


def insert(db, record):
    db.catalog_conn.execute(
        "INSERT INTO food_swap_requests(request_id, assignment_id, coach_account_id, player_account_id, "
        "target_json, reason, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
        (record["request_id"], record["assignment_id"], record["coach_account_id"],
         record["player_account_id"], json.dumps(record["food_swap"]), record["reason"], record["created_at"]),
    )


def claim(db, resolution):
    return db.catalog_conn.execute(
        "UPDATE food_swap_requests SET status=?, response=?, resolved_by=?, resolved_at=? "
        "WHERE request_id=? AND status='pending'",
        (resolution["status"], resolution["response"], resolution["resolved_by"],
         resolution["resolved_at"], resolution["request_id"]),
    ).rowcount == 1


def reopen_failed_apply(db, request_id):
    with db.catalog_transaction(immediate=True):
        row = db.catalog_conn.execute(
            "SELECT a.status, a.ended_at, a.ended_by FROM food_swap_requests r "
            "JOIN assignments a ON a.assignment_id=r.assignment_id "
            "WHERE r.request_id=? AND r.status='applied'", (request_id,),
        ).fetchone()
        if row is None:
            return
        active = row[0] == "active"
        db.catalog_conn.execute(
            "UPDATE food_swap_requests SET status=?, response=NULL, resolved_at=?, resolved_by=? "
            "WHERE request_id=? AND status='applied'",
            ("pending" if active else "closed", None if active else row[1],
             None if active else row[2], request_id),
        )
