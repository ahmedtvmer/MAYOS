"""Coach-owned Program templates stored in the shared catalog (ticket #305).

A template is catalog-side and player-free: it holds a name, an optional
description, and a normalized Program draft shape. Every read and write is
scoped to the owning coach in SQL, so an unknown id and another coach's id are
indistinguishable to callers.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

PROGRAM_TEMPLATE_COLUMNS = (
    "template_id, coach_account_id, name, description, program_json, "
    "archived_at, created_at, updated_at"
)


@dataclass(frozen=True)
class ProgramTemplateCreate:
    name: str
    description: str | None
    program: dict[str, Any]


class RegistryProgramTemplatesMixin:
    def create_program_template(
        self, coach_account_id: str, fields: ProgramTemplateCreate
    ) -> dict[str, Any]:
        template_id = f"tmpl:{uuid.uuid4()}"
        now = datetime.now(UTC).isoformat()
        with self.catalog_transaction(immediate=True):
            self.catalog_conn.execute(
                "INSERT INTO program_templates "
                "(template_id, coach_account_id, name, description, program_json, "
                "archived_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    template_id,
                    str(coach_account_id),
                    fields.name,
                    fields.description,
                    json.dumps(fields.program, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_program_template(coach_account_id, template_id)

    def get_program_template(
        self, coach_account_id: str, template_id: str
    ) -> dict[str, Any] | None:
        with self._catalog_lock:
            row = self.catalog_conn.execute(
                f"SELECT {PROGRAM_TEMPLATE_COLUMNS} FROM program_templates "
                "WHERE coach_account_id = ? AND template_id = ?",
                (str(coach_account_id), str(template_id)),
            ).fetchone()
        return self._program_template_from_row(row)

    def list_program_templates(
        self, coach_account_id: str, *, archived: bool = False
    ) -> list[dict[str, Any]]:
        archived_clause = "IS NOT NULL" if archived else "IS NULL"
        with self._catalog_lock:
            rows = self.catalog_conn.execute(
                f"SELECT {PROGRAM_TEMPLATE_COLUMNS} FROM program_templates "
                f"WHERE coach_account_id = ? AND archived_at {archived_clause} "
                "ORDER BY created_at DESC, template_id",
                (str(coach_account_id),),
            ).fetchall()
        return [self._program_template_from_row(row) for row in rows]

    def update_program_template(
        self,
        coach_account_id: str,
        template_id: str,
        *,
        name: str,
        description: str | None,
        program: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self.catalog_transaction(immediate=True):
            cursor = self.catalog_conn.execute(
                "UPDATE program_templates SET name = ?, description = ?, "
                "program_json = ?, updated_at = ? "
                "WHERE coach_account_id = ? AND template_id = ?",
                (
                    name,
                    description,
                    json.dumps(program, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                    str(coach_account_id),
                    str(template_id),
                ),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_program_template(coach_account_id, template_id)

    def set_program_template_archived(
        self, coach_account_id: str, template_id: str, *, archived: bool
    ) -> dict[str, Any] | None:
        archived_at = datetime.now(UTC).isoformat() if archived else None
        with self.catalog_transaction(immediate=True):
            cursor = self.catalog_conn.execute(
                "UPDATE program_templates SET archived_at = ?, updated_at = ? "
                "WHERE coach_account_id = ? AND template_id = ?",
                (
                    archived_at,
                    datetime.now(UTC).isoformat(),
                    str(coach_account_id),
                    str(template_id),
                ),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_program_template(coach_account_id, template_id)

    @staticmethod
    def _program_template_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "template_id": str(row[0]),
            "coach_account_id": str(row[1]),
            "name": str(row[2]),
            "description": row[3],
            "program": json.loads(row[4]),
            "archived_at": row[5],
            "created_at": str(row[6]),
            "updated_at": str(row[7]),
        }
