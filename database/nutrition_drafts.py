"""Assignment-keyed, private Nutrition drafts in the Player ledger."""

import json
from datetime import UTC, datetime


NUTRITION_DRAFTS_DDL = """
CREATE TABLE IF NOT EXISTS nutrition_plan_drafts (
    assignment_id TEXT PRIMARY KEY,
    draft_json TEXT NOT NULL,
    source_targets_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
)
"""


def read_draft(ledger, assignment_id):
    row = ledger.conn.execute(
        "SELECT * FROM nutrition_plan_drafts WHERE assignment_id=?", (assignment_id,)
    ).fetchone()
    if row is None:
        return None
    return {"draft": json.loads(row["draft_json"]), "revision": row["revision"],
            "updated_at": row["updated_at"],
            "source_targets": json.loads(row["source_targets_json"])}


def create_draft(ledger, assignment_id, draft, source_targets):
    ledger.conn.execute(
        "INSERT INTO nutrition_plan_drafts(assignment_id, draft_json, source_targets_json, updated_at) "
        "VALUES(?, ?, ?, ?)",
        (assignment_id, json.dumps(draft), json.dumps(source_targets), datetime.now(UTC).isoformat()),
    )


def save_draft(ledger, assignment_id, draft, revision):
    cursor = ledger.conn.execute(
        "UPDATE nutrition_plan_drafts SET draft_json=?, revision=revision+1, updated_at=? "
        "WHERE assignment_id=? AND revision=?",
        (json.dumps(draft), datetime.now(UTC).isoformat(), assignment_id, revision),
    )
    return cursor.rowcount == 1


def discard_draft(ledger, assignment_id):
    ledger.conn.execute("DELETE FROM nutrition_plan_drafts WHERE assignment_id=?", (assignment_id,))
    ledger._commit_ledger()
