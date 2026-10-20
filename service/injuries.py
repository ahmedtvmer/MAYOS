"""Player injury record operations shared by Profile, chat, and Coach reads."""

from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import UTC, datetime
from typing import Any

from core.injuries import (
    INJURY_BODY_AREAS,
    INJURY_STATUSES,
    body_area_in_text,
    is_none_answer,
    injury_body_parts,
    normalize_body_area,
    render_injury_record,
)
from database.shared import _normalize_exercise_name
from service import profile_change_alerts
from service.text_normalization import normalize_digits

MAX_INJURY_DESCRIPTION_LENGTH = 2000
LEGACY_INJURY_SOURCE_EVENT_KEY = "migration:v28:legacy-profile"
CLEARANCE_VERDICTS = ("cleared", "not_cleared", "cleared_with_limits")
MAX_CLEARANCE_NOTE_LENGTH = 1000
MAX_EXERCISE_FOLLOWUP_QUESTIONS = 2

_INTERNAL_INJURY_FIELDS = (
    "physician_followup_asked_at",
    "physician_followup_pending",
    "resolution_pending",
    "pending_exercise_id",
    "pending_exercise_name",
    "exercise_followup_asked_count",
)

_SHORT_AREA_REPLY_RE = re.compile(
    r"^(?:left|right|upper|lower|middle|front|side|area|joint|here|there|same|"
    r"not\s+sure|i\s+don['’]?t\s+know)(?:\s+(?:side|area|joint|spot|place))?[.!]*$",
    re.IGNORECASE,
)


class InjuryValidationError(ValueError):
    """An injury record contains an unsupported area, description, or status."""


@dataclass(frozen=True)
class LegacyInjuryImport:
    player_account_id: str | None
    injury_text: Any
    client_context: Any = None


def list_injuries(ledger: Any) -> list[dict[str, Any]]:
    records = []
    for record in ledger.list_injury_records():
        rendered = render_public_injury_record(record)
        rendered["clearances"] = ledger.list_exercise_clearances(str(record["id"]))
        records.append(rendered)
    return records


def render_public_injury_record(record: dict[str, Any]) -> dict[str, Any]:
    """Renders an injury without the state used only by chat routing."""
    rendered = render_injury_record(record)
    for internal_field in _INTERNAL_INJURY_FIELDS:
        rendered.pop(internal_field, None)
    return rendered


def list_exercise_clearances(ledger: Any, injury_id: str) -> list[dict[str, Any]]:
    return ledger.list_exercise_clearances(injury_id)


def _validated_clearance(verdict: Any, note: Any) -> tuple[str, str | None]:
    normalized = str(verdict or "").strip()
    if normalized not in CLEARANCE_VERDICTS:
        raise InjuryValidationError(f"Verdict must be one of: {', '.join(CLEARANCE_VERDICTS)}.")
    cleaned_note = str(note).strip() if note is not None else None
    if cleaned_note == "":
        cleaned_note = None
    if cleaned_note and len(cleaned_note) > MAX_CLEARANCE_NOTE_LENGTH:
        raise InjuryValidationError("Clearance note is too long.")
    return normalized, cleaned_note


def _validated_original_wording(value: Any) -> str:
    wording = str(value or "").strip()
    if not wording or len(wording) > MAX_INJURY_DESCRIPTION_LENGTH:
        raise InjuryValidationError("Original wording must be between 1 and 2000 characters.")
    return wording


def create_exercise_clearance(
    db: Any,
    ledger: Any,
    injury_id: str,
    *,
    player_account_id: str | None,
    exercise_name: str,
    original_wording: str,
    verdict: str,
    note: str | None = None,
    exercise_id: str | None = None,
    source_event_key: str | None = None,
    client: Any = None,
) -> dict[str, Any] | None:
    if ledger.get_injury_record(injury_id) is None:
        return None
    clean_name = str(exercise_name or "").strip()
    if not clean_name or len(clean_name) > 200:
        raise InjuryValidationError("Exercise name must be between 1 and 200 characters.")
    wording = _validated_original_wording(original_wording)
    clean_verdict, clean_note = _validated_clearance(verdict, note)
    clearance, created = ledger.create_exercise_clearance(
        injury_id=injury_id,
        exercise_id=exercise_id,
        exercise_name=clean_name,
        original_wording=wording,
        verdict=clean_verdict,
        note=clean_note,
        source_event_key=source_event_key,
    )
    if created and clearance:
        profile_change_alerts.record_clearance_change(
            db, player_account_id, clearance, change="created", client=client
        )
    return clearance


def update_exercise_clearance(
    db: Any,
    ledger: Any,
    clearance_id: str,
    *,
    player_account_id: str | None,
    exercise_name: str,
    original_wording: str,
    verdict: str,
    note: str | None = None,
    client: Any = None,
) -> dict[str, Any] | None:
    before = ledger.get_exercise_clearance(clearance_id)
    if before is None:
        return None
    clean_verdict, clean_note = _validated_clearance(verdict, note)
    wording = _validated_original_wording(original_wording)
    name = str(exercise_name or "").strip()
    if not name or len(name) > 200:
        raise InjuryValidationError("Exercise name must be between 1 and 200 characters.")
    if wording != before["original_wording"]:
        raise InjuryValidationError("Original player wording cannot be changed.")
    if before.get("exercise_id") is not None and name != before["exercise_name"]:
        raise InjuryValidationError("A catalog exercise name cannot be changed.")
    after = ledger.update_exercise_clearance(
        clearance_id,
        exercise_name=name,
        original_wording=wording,
        verdict=clean_verdict,
        note=clean_note,
    )
    if after is not None and any(before.get(key) != after.get(key) for key in (
        "exercise_name", "original_wording", "verdict", "note"
    )):
        profile_change_alerts.record_clearance_change(
            db, player_account_id, after, change="updated", client=client
        )
    return after


def delete_exercise_clearance(
    db: Any,
    ledger: Any,
    clearance_id: str,
    *,
    player_account_id: str | None,
    client: Any = None,
) -> bool:
    before = ledger.get_exercise_clearance(clearance_id)
    deleted = ledger.delete_exercise_clearance(clearance_id)
    if deleted and before:
        profile_change_alerts.record_clearance_change(
            db, player_account_id, before, change="deleted", client=client
        )
    return deleted


_CLEARANCE_NEGATIVE_RE = re.compile(
    r"\b(?:no|not\s+cleared|not\s+allowed|avoid|shouldn['’]?t|can['’]?t\s+do|cannot\s+do|forbidden)\b|مش\s+مسموح|ممنوع",
    re.IGNORECASE,
)
_CLEARANCE_LIMITS_RE = re.compile(
    r"\b(?:with\s+limits?|limited|modify|modified|only\s+if|partial\s+range|light\s+weight)\b|بحدود|بأوزان\s+خفيفة",
    re.IGNORECASE,
)
_CLEARANCE_POSITIVE_RE = re.compile(
    r"\b(?:cleared|approved|okay\s+to|ok\s+to|allowed\s+to|can\s+do|safe\s+to)\b|مسموح",
    re.IGNORECASE,
)
_PHYSICIAN_PREFIX_RE = re.compile(
    r"^(?:(?:my|the)\s+)?(?:physician|doctor|clinician)\s+(?:said|told\s+me|advised\s+me|cleared(?:\s+me)?\s+to|cleared|approved)\s+",
    re.IGNORECASE,
)


def parse_clearance_statement(message: str, pending_exercise_name: str | None = None) -> dict[str, str] | None:
    """Extracts only explicit player wording; the model never supplies this verdict."""
    text = message.strip()
    if not text:
        return None
    if _CLEARANCE_LIMITS_RE.search(text):
        verdict = "cleared_with_limits"
        note_match = re.search(r"\b(?:with\s+limits?|limited|modify|only\s+if)\b\s*(.*)$", text, re.I)
        note = note_match.group(1).strip(" .,!?") if note_match else None
    elif _CLEARANCE_NEGATIVE_RE.search(text):
        verdict, note = "not_cleared", None
    elif _CLEARANCE_POSITIVE_RE.search(text):
        verdict, note = "cleared", None
    else:
        return None

    exercise = _PHYSICIAN_PREFIX_RE.sub("", text)
    exercise = re.sub(r"^(?:the\s+)?(?:exercise\s+)?", "", exercise, flags=re.I)
    exercise = re.sub(
        r"^(?:no|not\s+cleared|not\s+allowed|avoid|shouldn['’]?t|can['’]?t\s+do|cannot\s+do|cleared|approved|okay\s+to|ok\s+to|allowed\s+to|can\s+do|safe\s+to)\s+",
        "", exercise, flags=re.I,
    )
    exercise = re.sub(
        r"\s+(?:is|are)?\s*(?:not\s+cleared|not\s+allowed|cleared|approved|okay|safe|with\s+limits?|limited).*$",
        "", exercise, flags=re.I,
    ).strip(" .,!?")
    exercise = re.sub(r"^(?:me\s+to|to)\s+", "", exercise, flags=re.I)
    if not exercise and pending_exercise_name:
        exercise = pending_exercise_name
    if not exercise or re.match(
        r"^(?:i|me|my|we|you|he|she|they|physician|doctor|clinician|injury|pain)\b",
        exercise,
        re.I,
    ):
        return None
    return {"exercise_name": exercise, "verdict": verdict, "note": note or ""}


def resolve_exercise_matches(store: Any, exercise_name: str) -> list[dict[str, Any]]:
    matches = store.find_exercises_by_name(exercise_name, limit=None)
    if matches:
        return _distinct_exercises(matches)
    from core.embeddings import get_embedding_model

    candidates = store.search_similar_exercises(
        get_embedding_model().embed_query(exercise_name), limit=12
    )
    return [candidate for candidate in candidates if float(candidate.get("distance", 1.0)) <= 0.27]


def _distinct_exercises(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for candidate in matches:
        unique.setdefault(str(candidate.get("id")), candidate)
    return list(unique.values())


def source_event_key(ledger: Any, message: str) -> str | None:
    history = ledger.get_chat_history()
    if history and history[-1].get("role") == "user" and history[-1].get("content") == message:
        return f"clearance-chat:{history[-1]['id']}"
    return None


def pending_clearance_question(ledger: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for injury in ledger.list_injury_records():
        pending = ledger.get_pending_exercise_clearance(str(injury["id"]))
        if pending:
            return injury, pending
    return None


def pending_exercise_followup(ledger: Any) -> dict[str, Any] | None:
    return next(
        (injury for injury in ledger.list_injury_records()
         if injury.get("status") != "resolved" and injury.get("pending_exercise_id")),
        None,
    )


def choose_clearance_candidate(candidates: list[dict[str, Any]], reply: str) -> dict[str, Any] | None:
    normalized_reply = normalize_digits(reply)
    number = re.fullmatch(
        r"(?:(?:the\s+)?(?:number\s*)?(\d{1,2})(?:st|nd|rd|th)?|"
        r"(?:اختيار|الاختيار|رقم)\s*(\d{1,2}))[.!?؟]*",
        normalized_reply.strip(),
        re.I,
    )
    if number:
        index = int(number.group(1) or number.group(2)) - 1
        if 0 <= index < len(candidates):
            return candidates[index]
    normalized = _normalize_exercise_name(reply)
    hits = [
        item
        for item in candidates
        if (name := _normalize_exercise_name(str(item.get("name", ""))))
        and name in normalized
    ]
    return hits[0] if len(hits) == 1 else None


def matching_program_exercise(ledger: Any, store: Any, injury: dict[str, Any]) -> dict[str, Any] | None:
    area = normalize_body_area(injury.get("body_area"))
    body_parts = {part.casefold() for part in injury_body_parts(area)}
    program = ledger.get_active_program()
    if program is None or not body_parts:
        return None
    cleared = {
        str(item.get("exercise_id")) for item in ledger.list_exercise_clearances(str(injury["id"]))
        if item.get("exercise_id")
    }
    pending_id = injury.get("pending_exercise_id")
    if pending_id:
        return {"id": str(pending_id), "name": injury.get("pending_exercise_name") or str(pending_id)}
    for day in getattr(program, "days", ()) or ():
        for exercise in getattr(day, "exercises", ()) or ():
            exercise_id = str(getattr(exercise, "exercise_id", ""))
            if not exercise_id or exercise_id in cleared:
                continue
            entry = store.get_exercise_library_entry(exercise_id)
            if entry and str(entry.get("body_part") or "").casefold() in body_parts:
                return {"id": exercise_id, "name": str(entry.get("name") or getattr(exercise, "exercise_name", exercise_id))}
    return None


def pending_physician_followup(ledger: Any, query: str) -> dict[str, Any] | None:
    records = ledger.list_injury_records()
    for injury in records:
        if injury.get("status") != "reported":
            continue
        asked = injury.get("physician_followup_asked_at")
        advice_for_area = bool(
            injury.get("body_area")
            and normalize_body_area(injury.get("body_area")) == body_area_in_text(query)
            and re.search(r"\b(?:train|training|workout|exercise|lift|squat|run|program|safe|should|can\s+i|could\s+i)\b", query, re.I)
        )
        if not asked or advice_for_area:
            return injury
    return None


def pending_physician_followup_answer(ledger: Any) -> dict[str, Any] | None:
    return next(
        (injury for injury in ledger.list_injury_records()
         if injury.get("status") == "reported" and injury.get("physician_followup_pending")),
        None,
    )


def mark_physician_followup_asked(ledger: Any, injury_id: str) -> None:
    ledger.mark_physician_followup_asked(injury_id, datetime.now(UTC).isoformat())


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
        if next_status != "reported":
            ledger.set_physician_followup_pending(injury_id, False)
        if next_status == "resolved":
            ledger.set_resolution_pending(injury_id, False)
            ledger.clear_pending_exercise_followup(injury_id)
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
_FULL_PHYSICIAN_CLEARANCE_RE = re.compile(
    r"\b(?:physician|doctor|clinician)\b[^.!?]{0,50}\b(?:"
    r"i(?:['’]m| am| have been| was)\s+(?:fully|completely)\s+cleared|"
    r"(?:fully|completely)\s+cleared\s+(?:me|my(?:\s+[a-z]+)?\s+injury|the injury|my recovery)|"
    r"cleared\s+(?:me|my(?:\s+[a-z]+)?\s+injury|the injury|my recovery)\s+(?:fully|completely)"
    r")\b|"
    r"\b(?:fully|completely)\s+cleared\s+(?:me|my(?:\s+[a-z]+)?\s+injury|the injury|my recovery)\s+"
    r"by\s+(?:my\s+)?(?:physician|doctor|clinician)\b|"
    r"الدكتور\s+(?:أكد|قال)\s+إن(?:ي|ني)\s+اتعافيت\s+تمامًا",
    re.IGNORECASE,
)
_CONFIRM_RE = re.compile(
    r"^(?:yes|yeah|yep|confirm|confirmed|i confirm|تمام|أيوه|ايوه|نعم)[.!\s]*$", re.I
)
_DECLINE_RE = re.compile(
    r"^(?:no|nope|not yet|cancel|don't|do not|لأ|لا|مش دلوقتي)[.!\s]*$", re.I
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
    if _PHYSICIAN_SEEN_RE.search(message):
        return "physician_seen"
    return None


def full_physician_clearance(message: str) -> bool:
    return bool(_FULL_PHYSICIAN_CLEARANCE_RE.search(message))


def pending_resolution(ledger: Any) -> dict[str, Any] | None:
    for record in ledger.list_injury_records():
        if record.get("resolution_pending"):
            return record
    return None


def confirmation_reply(message: str) -> bool | None:
    if _CONFIRM_RE.fullmatch(message.strip()):
        return True
    if _DECLINE_RE.fullmatch(message.strip()):
        return False
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
