"""Player injury record operations shared by Profile, chat, and Coach reads."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from core.injuries import (
    INJURY_BODY_AREAS,
    INJURY_STATUSES,
    body_area_in_text,
    is_none_answer,
    normalize_body_area,
    render_injury_record,
)
from service import profile_change_alerts

MAX_INJURY_DESCRIPTION_LENGTH = 2000
LEGACY_INJURY_SOURCE_EVENT_KEY = "migration:v28:legacy-profile"

class InjuryValidationError(ValueError):
    """An injury record contains an unsupported area, description, or status."""


@dataclass(frozen=True)
class LegacyInjuryImport:
    player_account_id: str | None
    injury_text: Any
    client_context: Any = None


def list_injuries(ledger: Any) -> list[dict[str, Any]]:
    return [render_injury_record(record) for record in ledger.list_injury_records()]


def pending_clarification(ledger: Any) -> dict[str, Any] | None:
    """Return a real pending injury row, ignoring dynamically mocked methods."""
    try:
        record = ledger.get_pending_injury_clarification()
    except AttributeError:
        return None
    return record if type(record) is dict else None


def _validated_description(value: Any) -> str:
    description = str(value or "").strip()
    if not description or len(description) > MAX_INJURY_DESCRIPTION_LENGTH:
        raise InjuryValidationError("Description must be between 1 and 2000 characters.")
    return description


def _validated_area(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and value.strip().casefold() in {"", "unknown"}):
        return None
    area = normalize_body_area(value)
    if area is None:
        raise InjuryValidationError(f"Body area must be one of: {', '.join(INJURY_BODY_AREAS)}.")
    return area


def create_injury(
    db: Any,
    ledger: Any,
    *,
    player_account_id: str | None,
    body_area: Any,
    description: Any,
    source_event_key: str | None = None,
    clarification_pending: bool = False,
    client: Any = None,
) -> dict[str, Any]:
    area = _validated_area(body_area)
    detail = _validated_description(description)
    record, created = ledger.create_injury_record(
        area,
        detail,
        clarification_pending=clarification_pending and area is None,
        source_event_key=source_event_key,
    )
    if created:
        _sync_legacy_limitations(ledger)
        profile_change_alerts.record_injury_change(
            db,
            player_account_id,
            record,
            change="created",
            client=client,
        )
    return render_injury_record(record)


def import_legacy_injury_text(
    db: Any,
    ledger: Any,
    command: LegacyInjuryImport,
) -> dict[str, Any] | None:
    """Imports legacy free text through the same idempotent slot as v28."""
    description = str(command.injury_text or "").strip()
    if is_none_answer(description):
        _sync_legacy_limitations(ledger)
        return None

    area = body_area_in_text(description)
    record, created = ledger.create_injury_record(
        area,
        description,
        source_event_key=LEGACY_INJURY_SOURCE_EVENT_KEY,
    )
    if created:
        return _record_imported_injury(db, ledger, record, command)

    if record.get("description") != description or record.get("body_area") != area:
        return _update_imported_injury(db, ledger, record, command)

    _sync_legacy_limitations(ledger)
    return render_injury_record(record)


def _record_imported_injury(
    db: Any,
    ledger: Any,
    record: dict[str, Any],
    command: LegacyInjuryImport,
) -> dict[str, Any]:
    _sync_legacy_limitations(ledger)
    profile_change_alerts.record_injury_change(
        db,
        command.player_account_id,
        record,
        change="created",
        client=command.client_context,
    )
    return render_injury_record(record)


def _update_imported_injury(
    db: Any,
    ledger: Any,
    record: dict[str, Any],
    command: LegacyInjuryImport,
) -> dict[str, Any]:
    description = str(command.injury_text or "").strip()
    after = ledger.update_injury_record(
        str(record["id"]),
        body_area=body_area_in_text(description),
        update_body_area=True,
        description=description,
        status="reported",
        clarification_pending=False,
    )
    if after is None:
        return render_injury_record(record)
    _sync_legacy_limitations(ledger)
    profile_change_alerts.record_injury_change(
        db,
        command.player_account_id,
        after,
        change="updated",
        previous_status=record.get("status"),
        client=command.client_context,
    )
    return render_injury_record(after)


def update_injury(
    db: Any,
    ledger: Any,
    injury_id: str,
    *,
    player_account_id: str | None,
    body_area: Any,
    description: Any,
    status: Any,
    client: Any = None,
) -> dict[str, Any] | None:
    before = ledger.get_injury_record(injury_id)
    if before is None:
        return None
    area = _validated_area(body_area)
    detail = _validated_description(description)
    next_status = str(status or "").strip()
    if next_status not in INJURY_STATUSES:
        raise InjuryValidationError(f"Status must be one of: {', '.join(INJURY_STATUSES)}.")
    after = ledger.update_injury_record(
        injury_id,
        body_area=area,
        update_body_area=True,
        description=detail,
        status=next_status,
        clarification_pending=False,
    )
    if after is None:
        return None
    if any(before.get(field) != after.get(field) for field in ("body_area", "description", "status")):
        _sync_legacy_limitations(ledger)
    if before.get("status") != after.get("status"):
        profile_change_alerts.record_injury_change(
            db,
            player_account_id,
            after,
            change="status_changed",
            previous_status=before.get("status"),
            client=client,
        )
    return render_injury_record(after)


def _sync_legacy_limitations(ledger: Any) -> None:
    """Keeps old program builders and clients on a bounded active-record projection."""
    ledger.sync_legacy_injuries_projection()


_PHYSICIAN_SEEN_RE = re.compile(
    r"\b(?:saw|seen|visited|consulted|checked\s+by)\s+(?:a\s+)?(?:physician|doctor|clinician)\b|"
    r"\b(?:physician|doctor|clinician)\s+(?:saw|examined|checked)\b|"
    r"(?:كشفت|كشف علي|رحت للدكتور|زرت الطبيب)",
    re.IGNORECASE,
)
_RESOLVED_RE = re.compile(
    r"\b(?:injury|pain)\b[^.!?]{0,30}\b(?:resolved|healed|recovered|no\s+longer\s+hurts|"
    r"pain\s+is\s+gone)\b|"
    r"\b(?:resolved|healed|recovered)\b[^.!?]{0,20}\b(?:injury|pain)\b|"
    r"\b(?:my\s+)?pain\s+(?:is\s+)?gone\b|"
    r"(?:مفيش\s+ألم|مبقاش\s+في\s+ألم|مبقتش\s+بتوجع)",
    re.IGNORECASE,
)
_RESOLVED_WORD_RE = re.compile(
    r"\b(?:resolved|healed|recovered|no\s+longer\s+hurts|pain\s+is\s+gone)\b|"
    r"(?:خفيت|اتعافيت|مبقتش\s+بتوجع|مفيش\s+ألم)",
    re.IGNORECASE,
)


def update_from_chat(
    db: Any,
    ledger: Any,
    *,
    player_account_id: str | None,
    message: str,
    client: Any = None,
) -> dict[str, Any] | None:
    """Applies explicit physician-seen/resolved statements to a matching record."""
    status = _status_from_message(message)
    if status is None:
        return None
    area = body_area_in_text(message)
    record = _latest_active_injury(ledger, area)
    if record is None:
        return None
    return update_injury(
        db,
        ledger,
        str(record["id"]),
        player_account_id=player_account_id,
        body_area=record["body_area"],
        description=record["description"],
        status=status,
        client=client,
    )


def has_matching_status_update(ledger: Any, message: str) -> bool:
    """Only route a status update when a real active injury record can match it."""
    status = _status_from_message(message)
    if status is None:
        return False
    return _latest_active_injury(ledger, body_area_in_text(message)) is not None


def _status_from_message(message: str) -> str | None:
    if _RESOLVED_RE.search(message) or (
        body_area_in_text(message) is not None and _RESOLVED_WORD_RE.search(message)
    ):
        return "resolved"
    if _PHYSICIAN_SEEN_RE.search(message):
        return "physician_seen"
    return None


def _latest_active_injury(ledger: Any, area: str | None) -> dict[str, Any] | None:
    try:
        record = ledger.get_latest_active_injury(area)
    except AttributeError:
        return None
    return record if type(record) is dict else None


def record_clarified_area(ledger: Any, injury_id: str, area: str) -> None:
    ledger.update_injury_record(
        injury_id,
        body_area=area,
        update_body_area=True,
        clarification_pending=False,
    )


def consume_pending_clarification(ledger: Any, injury_id: str) -> None:
    """Closes an unanswered area question after the player moves on."""
    ledger.update_injury_record(injury_id, clarification_pending=False)


def record_from_clinical_message(
    db: Any,
    ledger: Any,
    *,
    player_account_id: str | None,
    message: str,
) -> None:
    """Record a clinical chat turn, deduping retries by the persisted chat row."""
    updated = update_from_chat(
        db,
        ledger,
        player_account_id=player_account_id,
        message=message,
    )
    if updated is not None:
        return
    area = body_area_in_text(message)
    create_injury(
        db,
        ledger,
        player_account_id=player_account_id,
        body_area=area,
        description=message,
        source_event_key=_clinical_source_event_key(ledger, message),
        clarification_pending=area is None,
    )


def _clinical_source_event_key(ledger: Any, message: str) -> str | None:
    history = ledger.get_chat_history()
    if not history or history[-1].get("role") != "user" or history[-1].get("content") != message:
        return None
    return f"chat:{history[-1]['id']}"
