"""RegistryPlansMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

from datetime import UTC, datetime
from typing import Any


class RegistryPlansMixin:
    _PLAN_COLUMNS = "account_id, capability, plan, status, updated_at"

    @staticmethod
    def _plan_from_row(row: Any) -> dict[str, Any]:
        return {
            "account_id": str(row[0]),
            "capability": str(row[1]),
            "plan": str(row[2]),
            "status": str(row[3]),
            "updated_at": str(row[4]),
        }

    def list_plans(self, account_id: str) -> list[dict[str, Any]]:
        """Lists every stored plan override for an immutable account id."""
        if not account_id:
            return []
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._PLAN_COLUMNS} FROM account_plans WHERE account_id = ? ORDER BY capability",
                (str(account_id),),
            )
            return [self._plan_from_row(row) for row in cursor.fetchall()]

    def set_plan(self, account_id: str, capability: str, plan: str, status: str = "active") -> None:
        """Upserts one capability's plan. Callers must check capability eligibility first."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                """
                INSERT INTO account_plans (account_id, capability, plan, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id, capability) DO UPDATE SET
                    plan = excluded.plan,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (str(account_id), str(capability), str(plan), str(status), now),
            )
            self.catalog_conn.commit()
