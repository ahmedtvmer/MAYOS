"""Privacy-safe analytics for committed program and request changes."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from service import analytics


@dataclass(frozen=True)
class ProgramAnalyticsActor:
    account_id: str
    role: str


def _program_version(program: Any) -> int:
    version = getattr(program, "version", None)
    if type(version) is not int or version < 1:
        raise ValueError("A persisted program version is required for analytics.")
    return version


def _program_owner_id(actor: ProgramAnalyticsActor, player_account_id: str | None) -> str:
    if actor.role == "coach" and not player_account_id:
        raise ValueError("The player's account id is required for coach program events.")
    return player_account_id or actor.account_id


def capture_program_generated(
    actor: ProgramAnalyticsActor,
    trigger: str,
    program: Any,
    *,
    player_account_id: str | None = None,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    owner_id = _program_owner_id(actor, player_account_id)
    version = _program_version(program)
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=actor.account_id,
            event="program_generated",
            domain_key=f"{owner_id}:program:{version}:generated",
            role=actor.role,
            properties={"trigger": trigger, "day_count": len(program.days)},
        ),
        client,
    )


def capture_coach_program_published(
    actor: ProgramAnalyticsActor,
    assignment_id: str,
    program: Any,
    first_for_assignment: bool,
    *,
    player_account_id: str,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    version = _program_version(program)
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=actor.account_id,
            event="coach_program_published",
            domain_key=f"{player_account_id}:publication:{assignment_id}:{version}",
            role=actor.role,
            properties={
                "day_count": len(program.days),
                "first_for_assignment": first_for_assignment,
                "is_coaching_action": True,
            },
        ),
        client,
    )


def capture_program_exercise_swapped(
    actor: ProgramAnalyticsActor,
    program: Any,
    *,
    player_account_id: str | None = None,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    owner_id = _program_owner_id(actor, player_account_id)
    version = _program_version(program)
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=actor.account_id,
            event="program_exercise_swapped",
            domain_key=f"{owner_id}:program:{version}:exercise_swap",
            role=actor.role,
        ),
        client,
    )


def capture_program_request_created(
    actor: ProgramAnalyticsActor,
    request_row: dict[str, Any],
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=actor.account_id,
            event="program_request_created",
            domain_key=f"{request_row['request_id']}:created",
            role=actor.role,
            properties={"kind": request_row["kind"]},
        ),
        client,
    )


def capture_program_request_resolved(
    actor: ProgramAnalyticsActor,
    request_row: dict[str, Any],
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    created = _parse_timestamp(request_row.get("created_at"))
    resolved = _parse_timestamp(request_row.get("resolved_at"))
    elapsed = 0 if created is None or resolved is None else max(0, int((resolved - created).total_seconds()))
    maximum = analytics.PROPERTY_TYPES["time_open_seconds"].maximum
    elapsed = min(elapsed, maximum) if maximum is not None else elapsed
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=actor.account_id,
            event="program_request_resolved",
            domain_key=f"{request_row['request_id']}:resolved",
            role=actor.role,
            properties={
                "outcome": request_row["status"],
                "time_open_seconds": elapsed,
                "is_coaching_action": actor.role == "coach",
            },
        ),
        client,
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
