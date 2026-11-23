"""The next days' workout reminders for a device that schedules them itself (#840).

Android schedules these as local notifications, so reminders fire offline.
They follow the Web Push reminder rules (#742): only on expected training
days, at the reminder time, deferred past quiet hours within the same day, and
never on a day already trained. Copy comes from the same supportive pool, with
no message repeated within five reminders.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from service.attendance import is_expected_day
from service.push_messages import ROUTES, choose_reminder
from service.schedule import timezone_for_versions
from service.training_status import TrainingStatusFacts, compute_training_status
from database import push as storage

PLAN_DAYS = 14


def _clock(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour, minute)


def _fire_time(day: date, prefs: dict[str, Any], zone: ZoneInfo) -> datetime | None:
    """The reminder time on ``day``, or the end of quiet hours that same day."""
    reminder = _clock(prefs["reminder_time"])
    start, end = _clock(prefs["quiet_start"]), _clock(prefs["quiet_end"])
    quiet = start != end and (start <= reminder < end if start < end else reminder >= start or reminder < end)
    if not quiet:
        return datetime.combine(day, reminder, tzinfo=zone)
    # Deferred within the day only, as the server sweep does; never to tomorrow.
    if end > reminder:
        return datetime.combine(day, end, tzinfo=zone)
    return None


def reminder_plan(db: Any, account: dict[str, Any], now: datetime, days: int = PLAN_DAYS) -> dict[str, Any]:
    prefs = storage.preferences(db, account["account_id"])
    with db.open_ledger(account["ledger_id"]) as ledger:
        versions = ledger.list_training_schedules(account["ledger_id"])
        timezone = timezone_for_versions(versions, prefs["timezone"])
        if not prefs["workout_reminders"]:
            return {"timezone": timezone, "reminders": []}
        zone = ZoneInfo(timezone)
        today = now.astimezone(zone).date()
        pauses = ledger.list_training_pauses(account["ledger_id"])
        performed = ledger.list_performed_dates()
        trained = {str(day)[:10] for day in performed}
        program = ledger.get_active_program_view()
        facts = TrainingStatusFacts(
            versions=versions, pauses=pauses, performed_dates=performed,
            weekly_frequency=int(program.weekly_frequency) if program else 0,
            local_today=today, mayos_workouts=len(performed),
        )
        streak = compute_training_status(facts).weekly_streak
        latest = max((date.fromisoformat(str(day)[:10]) for day in performed), default=None)
        reminders = []
        recent: list[str] = []
        for offset in range(days):
            day = today + timedelta(days=offset)
            if not is_expected_day(versions, pauses, day) or day.isoformat() in trained:
                continue
            fire_at = _fire_time(day, prefs, zone)
            if fire_at is None or fire_at <= now:
                continue
            returning = latest is not None and (day - latest).days >= 7
            template, body = choose_reminder(
                account.get("display_language") or "en", recent,
                session_ready=program is not None, streak=streak, returning=returning,
            )
            recent.insert(0, template)
            reminders.append({
                "date": day.isoformat(), "at": fire_at.isoformat(), "template": template,
                "title": "MAYOS", "body": body, "url": ROUTES["workout_reminder"],
            })
    return {"timezone": timezone, "reminders": reminders}
