"""Owner-scoped catalog storage, with no Player or Assignment references."""

import json
import uuid
from datetime import UTC, datetime

from database.food_library.lookup import _food, _named_rows


NUTRITION_TEMPLATES_DDL = """
CREATE TABLE IF NOT EXISTS nutrition_templates (
    template_id TEXT PRIMARY KEY,
    coach_account_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    nutrition_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nutrition_templates_owner
    ON nutrition_templates(coach_account_id, created_at);
"""


def _template(row):
    if row is None:
        return None
    template = dict(zip(("template_id", "coach_account_id", "name", "description",
                         "nutrition_json", "created_at", "updated_at"), row))
    template["nutrition"] = json.loads(template.pop("nutrition_json"))
    return template


def read(db, coach_id, template_id):
    with db._catalog_lock:
        row = db.catalog_conn.execute(
            "SELECT * FROM nutrition_templates WHERE coach_account_id=? AND template_id=?",
            (coach_id, template_id),
        ).fetchone()
    return _template(row)


def list_templates(db, coach_id):
    with db._catalog_lock:
        rows = db.catalog_conn.execute(
            "SELECT * FROM nutrition_templates WHERE coach_account_id=? ORDER BY created_at DESC, template_id",
            (coach_id,),
        ).fetchall()
    return [_template(row) for row in rows]


def create(db, coach_id, body):
    template_id = f"nutrition-tmpl:{uuid.uuid4()}"
    now = datetime.now(UTC).isoformat()
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute(
            "INSERT INTO nutrition_templates VALUES (?, ?, ?, ?, ?, ?, ?)",
            (template_id, coach_id, body["name"], body["description"],
             json.dumps(body["nutrition"], ensure_ascii=False), now, now),
        )
    return read(db, coach_id, template_id)


def update(db, coach_id, template_id, body):
    with db.catalog_transaction(immediate=True):
        changed = db.catalog_conn.execute(
            "UPDATE nutrition_templates SET name=?, description=?, nutrition_json=?, updated_at=? "
            "WHERE coach_account_id=? AND template_id=?",
            (body["name"], body["description"], json.dumps(body["nutrition"], ensure_ascii=False),
             datetime.now(UTC).isoformat(), coach_id, template_id),
        ).rowcount
    return read(db, coach_id, template_id) if changed else None


def delete(db, coach_id, template_id):
    with db.catalog_transaction(immediate=True):
        return db.catalog_conn.execute(
            "DELETE FROM nutrition_templates WHERE coach_account_id=? AND template_id=?",
            (coach_id, template_id),
        ).rowcount == 1


def foods(db):
    with db._catalog_lock:
        if not db.catalog_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='foods'"
        ).fetchone():
            return []
        rows = _named_rows(db.catalog_conn,
            "SELECT * FROM foods WHERE reviewed=1 AND hidden=0 "
            "AND staple_roles_json<>'[]' ORDER BY staple_order, id"
        )
    return [_food(row) for row in rows]
