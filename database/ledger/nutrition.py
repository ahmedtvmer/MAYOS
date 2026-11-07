"""Nutrition plan and private screening operations for a Training ledger."""

import json
from datetime import UTC, datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class NutritionPlanVersion:
    goal: str
    reason: dict
    intensity: str | None
    daily_activity: str
    targets: dict
    created_at: str | None = None
    goal_source_snapshot: dict | None = None
    author: str = "Player"
    provenance: str = "automatic"
    authority_assignment_id: str | None = None


@dataclass(frozen=True)
class NutritionSetup:
    sex: str
    daily_activity: str
    screening: dict
    plan: NutritionPlanVersion | None


class LedgerNutritionMixin:
    def change_water_glasses(self, entry_date, change):
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        if change > 0:
            row = self.conn.execute(
                "INSERT INTO water_log(entry_date, glass_count, updated_at) VALUES(?, 1, ?) "
                "ON CONFLICT(entry_date) DO UPDATE SET glass_count=glass_count+1, "
                "updated_at=excluded.updated_at WHERE glass_count < 30 "
                "RETURNING glass_count",
                (str(entry_date), now),
            ).fetchone()
        else:
            row = self.conn.execute(
                "UPDATE water_log SET glass_count=glass_count-1, updated_at=? "
                "WHERE entry_date=? AND glass_count > 0 RETURNING glass_count",
                (now, str(entry_date)),
            ).fetchone()
        if row is None:
            raise ValueError("Water glass count must be between 0 and 30.")
        updated = int(row[0])
        self._commit_ledger()
        return updated, now

    def get_water_glasses(self, entry_date):
        row = self.conn.execute(
            "SELECT glass_count FROM water_log WHERE entry_date=?", (str(entry_date),)
        ).fetchone()
        return int(row[0]) if row else 0

    def get_water_log_days(self, start_date, end_date):
        rows = self.conn.execute(
            "SELECT entry_date, glass_count FROM water_log WHERE entry_date BETWEEN ? AND ?",
            (str(start_date), str(end_date)),
        ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def upsert_nutrition_adherence(self, entry_date, value):
        updated_at = datetime.now(UTC).isoformat(timespec="microseconds")
        self.conn.execute(
            "INSERT INTO nutrition_adherence(entry_date, value, source, created_at) "
            "VALUES(?, ?, 'answered', ?) ON CONFLICT(entry_date) DO UPDATE SET "
            "value=excluded.value, source='answered', created_at=excluded.created_at",
            (str(entry_date), str(value), updated_at),
        )
        self._commit_ledger()
        return updated_at

    def replace_computed_nutrition_adherence(self, entry_date, verdict):
        if verdict is None:
            self.conn.execute(
                "DELETE FROM nutrition_adherence WHERE entry_date=? AND source='computed'",
                (str(entry_date),),
            )
        else:
            self.conn.execute(
                "INSERT INTO nutrition_adherence(entry_date, value, source, created_at) "
                "VALUES(?, ?, 'computed', ?) ON CONFLICT(entry_date) DO UPDATE SET "
                "value=excluded.value, created_at=excluded.created_at "
                "WHERE nutrition_adherence.source='computed' AND nutrition_adherence.value<>excluded.value",
                (str(entry_date), verdict, datetime.now(UTC).isoformat(timespec="microseconds")),
            )
        self._commit_ledger()

    def list_nutrition_adherence(self, start_date, end_date):
        rows = self.conn.execute(
            "SELECT entry_date, value, source FROM nutrition_adherence "
            "WHERE entry_date >= ? AND entry_date <= ? ORDER BY entry_date",
            (str(start_date), str(end_date)),
        ).fetchall()
        return [{"date": str(row[0]), "value": str(row[1]), "source": str(row[2])} for row in rows]

    def get_nutrition_profile(self):
        row = self.conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
        return dict(row) if row else None

    def get_nutrition_screening(self):
        return self.conn.execute(
            "SELECT answers_json, answered_at FROM nutrition_screening WHERE id=1"
        ).fetchone()

    def get_active_nutrition_plan(self):
        return self.conn.execute(
            "SELECT * FROM nutrition_plan_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def get_nutrition_plan_before(self, ends_at):
        # Parse instants so offsets and microseconds at local midnight stay exact.
        eligible = []
        for plan in self.conn.execute("SELECT * FROM nutrition_plan_versions").fetchall():
            created_at = datetime.fromisoformat(plan["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if created_at < ends_at:
                eligible.append((created_at, int(plan["id"]), plan))
        return max(eligible, key=lambda candidate: candidate[:2])[2] if eligible else None

    def get_nutrition_goal_offer_dismissal(self):
        return self.conn.execute(
            "SELECT offer_key FROM nutrition_goal_offer_dismissals WHERE id=1"
        ).fetchone()

    def get_nutrition_goal_offer_snapshot(self, plan_version_id):
        return self.conn.execute(
            "SELECT profile_json FROM nutrition_goal_offer_snapshots WHERE plan_version_id=?",
            (plan_version_id,),
        ).fetchone()

    def dismiss_nutrition_goal_offer(self, offer_key):
        self.conn.execute(
            "INSERT INTO nutrition_goal_offer_dismissals(id, offer_key, dismissed_at) VALUES(1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET offer_key=excluded.offer_key, dismissed_at=excluded.dismissed_at",
            (offer_key, datetime.now(UTC).isoformat()),
        )

    def get_first_nutrition_plan_created_at(self):
        row = self.conn.execute(
            "SELECT MIN(created_at) FROM nutrition_plan_versions"
        ).fetchone()
        return str(row[0]) if row and row[0] else None

    def get_nutrition_pace_proposal(self):
        row = self.conn.execute(
            "SELECT * FROM nutrition_pace_proposals ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        proposal = dict(row)
        proposal["payload"] = json.loads(proposal.pop("payload_json"))
        return proposal

    def get_last_nutrition_pace_check_date(self):
        row = self.conn.execute(
            "SELECT last_evaluated_on FROM nutrition_pace_check_state WHERE id=1"
        ).fetchone()
        return str(row[0]) if row else None

    def record_nutrition_pace_check(self, checked_on):
        self.conn.execute(
            "INSERT INTO nutrition_pace_check_state(id, last_evaluated_on) VALUES(1, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_evaluated_on=excluded.last_evaluated_on",
            (str(checked_on),),
        )

    def create_nutrition_pace_proposal(self, plan_version_id, payload, created_at):
        cursor = self.conn.execute(
            "INSERT INTO nutrition_pace_proposals(plan_version_id, payload_json, created_at) "
            "VALUES(?, ?, ?)",
            (plan_version_id, json.dumps(payload), str(created_at)),
        )
        return cursor.lastrowid

    def decide_nutrition_pace_proposal(self, proposal_id, decision, decided_by, decided_at):
        cursor = self.conn.execute(
            "UPDATE nutrition_pace_proposals SET status=?, decided_by=?, decided_at=? "
            "WHERE id=? AND status IN ('pending','stale')",
            (decision, decided_by, str(decided_at), proposal_id),
        )
        return cursor.rowcount == 1

    def get_nutrition_training_days(self, fallback=0):
        row = self.conn.execute(
            "SELECT weekly_frequency FROM training_programs WHERE is_active=1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return max(0, min(7, int(row[0] if row else fallback or 0)))

    def save_nutrition_setup(self, setup: NutritionSetup):
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "UPDATE user_profile SET gender=?, sex_confirmed=1, daily_activity=?, updated_at=? WHERE id=1",
            (setup.sex, setup.daily_activity, now),
        )
        self.conn.execute(
            "INSERT INTO nutrition_screening(id, answers_json, answered_at) VALUES(1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET answers_json=excluded.answers_json, answered_at=excluded.answered_at",
            (json.dumps(setup.screening), now),
        )
        if setup.plan is not None:
            self.save_nutrition_plan(NutritionPlanVersion(
                goal=setup.plan.goal, reason=setup.plan.reason, intensity=setup.plan.intensity,
                daily_activity=setup.plan.daily_activity, targets=setup.plan.targets, created_at=now,
                goal_source_snapshot=setup.plan.goal_source_snapshot,
                author=setup.plan.author, provenance=setup.plan.provenance,
                authority_assignment_id=setup.plan.authority_assignment_id,
            ))

    def save_nutrition_plan(self, plan: NutritionPlanVersion):
        self.conn.execute("UPDATE nutrition_pace_proposals SET status='stale' "
                          "WHERE status='pending'")
        cursor = self.conn.execute(
            "INSERT INTO nutrition_plan_versions(author, provenance, goal, goal_reason_data_json, intensity, daily_activity, targets_json, authority_assignment_id, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (plan.author, plan.provenance, plan.goal, json.dumps(plan.reason), plan.intensity, plan.daily_activity,
             json.dumps(plan.targets), plan.authority_assignment_id,
             plan.created_at or datetime.now(UTC).isoformat()),
        )
        if plan.goal_source_snapshot is not None:
            self.conn.execute(
                "INSERT INTO nutrition_goal_offer_snapshots(plan_version_id, profile_json) VALUES(?, ?)",
                (cursor.lastrowid, json.dumps(plan.goal_source_snapshot, sort_keys=True)),
            )
        return cursor.lastrowid

    def update_nutrition_activity(self, activity):
        self.conn.execute("UPDATE user_profile SET daily_activity=?, updated_at=? WHERE id=1",
                          (activity, datetime.now(UTC).isoformat()))
