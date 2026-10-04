"""Registry markers that deduplicate Coach read events by UTC day."""


class RegistryCoachAnalyticsMixin:
    def claim_coach_analytics_daily_marker(
        self,
        coach_account_id: str,
        event_kind: str,
        utc_day: str,
        assignment_id: str | None = None,
    ) -> bool:
        """Claims one Coach event marker, returning true only for its first insert."""
        self.ensure_account_schema()
        assignment_key = str(assignment_id or "")
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO coach_analytics_daily_markers"
                " (coach_account_id, assignment_id, event_kind, utc_day) VALUES (?, ?, ?, ?)",
                (str(coach_account_id), assignment_key, str(event_kind), str(utc_day)),
            )
            claimed = cursor.rowcount == 1
            self._commit_catalog()
            return claimed

    def prune_coach_analytics_daily_markers(self, before_utc_day: str) -> int:
        """Removes daily markers older than the UTC-day cutoff."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "DELETE FROM coach_analytics_daily_markers WHERE utc_day < ?",
                (str(before_utc_day),),
            )
            pruned = int(cursor.rowcount)
            self._commit_catalog()
            return pruned
