"""Structured, resumable player onboarding intake (ADR 021).

The module is the single source of truth for the named onboarding decisions the
domain supports: each field's name, type, allowed values/range, required/optional
status, the profile column it maps to, and any explanation shown to the player.
Validation, per-answer persistence, resume/progress, legacy prefill, the
onboarding privacy notice, and confirmation into the existing profile +
first-program path all live here.

Two disclosures are deliberately made explicit because the program code, not
guesswork, defines them:

* The male/female specialization is required profile context, but does not
  change the automatic split. This flow collects no custom split, so generation
  uses the deterministic frequency default from
  ``agent.program_blueprints.DEFAULT_SPLIT_BY_FREQUENCY`` (via
  ``agent.program_rules.get_default_split``); glute priority is an opt-in for
  any player.
* Relative leg/torso proportion is coaching context only (ADR 011) and is never
  read by program generation; it changes neither split nor volume.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from service import onboarding as onboarding_service
from service import analytics
from service import injuries as injuries_service
from service.program_analytics import ProgramAnalyticsActor, capture_program_generated
from service._base import ledger_scope
from service.messages import (
    register_intake_copy_message_allowlists,
    structured_message,
)
from service.profile_fields import PROFILE_REBUILD_FIELDS
from service.weight_history import player_local_date
from service.weight_limits import MAX_WEIGHT_KG, MIN_WEIGHT_KG
from service.weight_trend_alerts import evaluate_for_player
from utils.equipment_access import (
    BODYWEIGHT_ONLY,
    COMMERCIAL_GYM,
    EQUIPMENT_ACCESS_VALUES,
    HOME_GYM,
    map_equipment_access,
)

STATUS_IN_PROGRESS = "in_progress"
STATUS_CONFIRMING = "confirming"
STATUS_CONFIRMED = "confirmed"

MIN_TEXT_LENGTH = 2
MAX_TEXT_LENGTH = 500

SPECIALIZATION_FREQUENCY_DESCRIPTION = (
    "Full Body for 1-3 days, Upper/Lower for 4 days, and Upper/Lower plus PPL "
    "for 5 days. Glute priority is an optional choice for anyone."
)

#: The required specialization is profile context and does not select the
#: player's default split. Glute priority is an opt-in for any player.
SPECIALIZATION_EXPLANATION = (
    "Your specialization is required profile context and does not change your "
    "default training split. We use your weekly frequency: "
    f"{SPECIALIZATION_FREQUENCY_DESCRIPTION}"
)

PROPORTIONS_EXPLANATION = (
    "Relative leg and torso length is coaching context only. It does not change "
    "exercise selection, program structure, or training volume."
)

SPECIALIZATION_OPTION_DESCRIPTIONS: dict[str, str] = {
    "male": f"Default split by frequency: {SPECIALIZATION_FREQUENCY_DESCRIPTION}",
    "female": f"Default split by frequency: {SPECIALIZATION_FREQUENCY_DESCRIPTION}",
}

#: Captions for the relative proportion choices. Coaching context only (ADR 011).
PROPORTIONS_OPTION_DESCRIPTIONS: dict[str, str] = {
    "long_legs": "Longer legs, shorter torso",
    "balanced": "Proportional upper and lower body",
    "long_torso": "Longer torso, shorter legs",
}

#: Rep-preference effect, derived from ``agent.program_rules.REP_WINDOWS``.
REP_PREFERENCE_OPTION_DESCRIPTIONS: dict[str, str] = {
    "low": "Lower rep targets: compounds 5-8, isolation 8-12.",
    "balanced": "Default rep targets: compounds 6-10, isolation 10-15.",
    "high": "Higher rep targets: compounds 8-12, isolation 12-20.",
}


class IntakeError(Exception):
    """Base class for structured-intake failures. The route maps each subclass."""


class IntakeValidationError(IntakeError):
    """A submitted answer (or the confirmation set) is invalid -> HTTP 400."""


class IntakeDisclosureRequired(IntakeError):
    """Answers were submitted before the onboarding privacy notice -> HTTP 403."""


class IntakeAlreadyConfirmed(IntakeError):
    """The intake can no longer be edited because it is confirmed -> HTTP 409."""


class IntakeConfirmInProgress(IntakeError):
    """Another confirmation owns the claim; a concurrent caller gets HTTP 409."""


@dataclass(frozen=True)
class IntakeField:
    """One named onboarding decision and its domain contract."""

    name: str
    kind: str  # "enum" | "int" | "float" | "text"
    required: bool
    profile_key: str
    allowed: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    explanation: str | None = None
    hint: str | None = None
    examples: tuple[str, ...] = ()
    #: Player-facing description per allowed value, written from the actual
    #: generation rule for that value. Shown on the option card.
    option_descriptions: dict[str, str] = field(default_factory=dict)


#: Ordered list of fields the visual flow collects. Values and ranges reuse the
#: existing onboarding graph / profile schemas exactly; nothing is invented.
INTAKE_FIELDS: tuple[IntakeField, ...] = (
    IntakeField(
        "gender", "enum", True, "gender",
        allowed=("male", "female"), explanation=SPECIALIZATION_EXPLANATION,
        option_descriptions=SPECIALIZATION_OPTION_DESCRIPTIONS,
    ),
    IntakeField(
        "proportions", "enum", True, "proportions",
        allowed=("long_legs", "balanced", "long_torso"), explanation=PROPORTIONS_EXPLANATION,
        option_descriptions=PROPORTIONS_OPTION_DESCRIPTIONS,
    ),
    IntakeField("age", "int", True, "age", minimum=12, maximum=100),
    IntakeField("height_cm", "float", True, "height_cm", minimum=100, maximum=250),
    IntakeField(
        "weight_kg", "float", True, "weight_kg",
        minimum=MIN_WEIGHT_KG, maximum=MAX_WEIGHT_KG,
    ),
    IntakeField(
        "target_weight_kg", "float", False, "target_weight_kg",
        minimum=MIN_WEIGHT_KG, maximum=MAX_WEIGHT_KG,
    ),
    IntakeField("training_age_years", "float", True, "training_age_years", minimum=0, maximum=70),
    IntakeField(
        "current_goal", "text", True, "current_goal",
        hint="What are you training for right now?",
        examples=("build glutes and legs", "get stronger", "lose fat"),
    ),
    IntakeField(
        "long_term_goal", "text", True, "long_term_goal",
        hint="What do you want to achieve over the longer term?",
        examples=("stronger and more muscular", "stay healthy and pain-free"),
    ),
    IntakeField("weekly_frequency", "int", True, "weekly_frequency", minimum=1, maximum=5),
    IntakeField(
        "equipment_access", "enum", True, "equipment_access",
        allowed=EQUIPMENT_ACCESS_VALUES,
        option_descriptions={
            COMMERCIAL_GYM: "A fully equipped commercial gym.",
            HOME_GYM: "Equipment you keep at home, such as weights or machines.",
            BODYWEIGHT_ONLY: "No gym equipment; train with your bodyweight.",
        },
    ),
    IntakeField(
        "injuries_or_limitations", "text", True, "injuries_or_limitations",
        hint="List any injuries or limitations. 'None' is a valid answer.",
        examples=("None", "left knee pain on deep squats"),
    ),
    IntakeField(
        "stress_and_sleep", "text", True, "stress_and_sleep",
        hint="How are your stress and sleep?",
        examples=("moderate stress, 7 hours sleep", "low stress, 8 hours sleep"),
    ),
    IntakeField("rep_preference", "enum", False, "rep_preference", allowed=("low", "balanced", "high"),
                option_descriptions=REP_PREFERENCE_OPTION_DESCRIPTIONS),
)

FIELD_BY_NAME: dict[str, IntakeField] = {field.name: field for field in INTAKE_FIELDS}
REQUIRED_FIELDS: tuple[str, ...] = tuple(field.name for field in INTAKE_FIELDS if field.required)

#: Legacy three-step values that are unambiguous. ``balanced`` proportions is
#: the graph's fallback when the player never compared, so it is asked again
#: rather than treated as an answer. Likewise only an explicit low/high rep
#: preference is prefilled (the graph's ``balanced`` is an unstated default).
_LEGACY_UNAMBIGUOUS_PROPORTIONS = frozenset({"long_legs", "long_torso"})
_LEGACY_UNAMBIGUOUS_REP_PREFERENCES = frozenset({"low", "high"})


def _range_message(spec: IntakeField) -> str:
    if spec.minimum is not None and spec.maximum is not None:
        return f"between {spec.minimum:g} and {spec.maximum:g}"
    if spec.minimum is not None:
        return f">= {spec.minimum:g}"
    return f"<= {spec.maximum:g}"


def _intake_copy_message(code: str, fallback: str | None) -> dict[str, Any] | None:
    """Adds shared structured metadata without changing the English copy."""
    if fallback is None:
        return None
    return structured_message(code, {}, fallback)


def _program_message_metadata(message: str | None) -> dict[str, Any] | None:
    if message is None:
        return None
    return structured_message(
        "intake.program_generation_unavailable.v1", {}, message
    )


def _intake_option_slug(wire_value: str) -> str:
    """Maps a stable enum wire value to its readable metadata-code segment."""
    return re.sub(r"[^a-z0-9]+", "_", wire_value.lower()).strip("_")


def _intake_field_copy_codes(spec: IntakeField) -> tuple[str, ...]:
    codes = []
    for kind, copy_text in (("explanation", spec.explanation), ("hint", spec.hint)):
        if copy_text is not None:
            codes.append(f"intake.{spec.name}.{kind}.v1")
    codes.extend(
        f"intake.{spec.name}.example.{index}.v1"
        for index, _ in enumerate(spec.examples, start=1)
    )
    codes.extend(
        f"intake.{spec.name}.option.{_intake_option_slug(value)}.v1"
        for value in spec.option_descriptions
    )
    return tuple(codes)


INTAKE_COPY_MESSAGE_PARAM_ALLOWLISTS = {
    code: frozenset()
    for spec in INTAKE_FIELDS
    for code in _intake_field_copy_codes(spec)
}
register_intake_copy_message_allowlists(INTAKE_COPY_MESSAGE_PARAM_ALLOWLISTS)


def _validate_enum(spec: IntakeField, raw: Any, *, case_insensitive: bool = False) -> str:
    if not isinstance(raw, str):
        raise IntakeValidationError(
            f"Invalid value for '{spec.name}': must be one of {', '.join(spec.allowed)}."
        )
    value = raw.strip()
    if case_insensitive:
        value = next(
            (option for option in spec.allowed if option.casefold() == value.casefold()),
            value,
        )
    else:
        value = value.lower()
    if value not in spec.allowed:
        raise IntakeValidationError(
            f"Invalid value for '{spec.name}': must be one of {', '.join(spec.allowed)}."
        )
    return value


def _validate_number(spec: IntakeField, raw: Any, *, integer: bool) -> int | float:
    if isinstance(raw, bool):
        raise IntakeValidationError(f"Invalid value for '{spec.name}': must be a number.")
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*", raw)
        if not match:
            raise IntakeValidationError(f"Invalid value for '{spec.name}': must be a number.")
        value = float(match.group(1))
    else:
        raise IntakeValidationError(f"Invalid value for '{spec.name}': must be a number.")
    if not math.isfinite(value):
        raise IntakeValidationError(f"Invalid value for '{spec.name}': must be a finite number.")
    if integer and value != int(value):
        raise IntakeValidationError(f"Invalid value for '{spec.name}': must be a whole number.")
    result: int | float = int(value) if integer else value
    if spec.minimum is not None and result < spec.minimum:
        raise IntakeValidationError(
            f"Invalid value for '{spec.name}': must be {_range_message(spec)}."
        )
    if spec.maximum is not None and result > spec.maximum:
        raise IntakeValidationError(
            f"Invalid value for '{spec.name}': must be {_range_message(spec)}."
        )
    return result


def _validate_text(spec: IntakeField, raw: Any) -> str:
    if not isinstance(raw, str):
        raise IntakeValidationError(f"Invalid value for '{spec.name}': must be text.")
    value = raw.strip()
    if len(value) < MIN_TEXT_LENGTH:
        raise IntakeValidationError(
            f"Invalid value for '{spec.name}': must be at least {MIN_TEXT_LENGTH} characters."
        )
    if len(value) > MAX_TEXT_LENGTH:
        raise IntakeValidationError(
            f"Invalid value for '{spec.name}': must be at most {MAX_TEXT_LENGTH} characters."
        )
    return value


def validate_answer(field_name: str, raw: Any) -> Any:
    """Validates and normalizes one named answer, raising a field-specific error."""
    spec = FIELD_BY_NAME.get(field_name)
    if spec is None:
        raise IntakeValidationError(f"Unknown onboarding field '{field_name}'.")
    case_insensitive_enum = False
    if field_name == "equipment_access":
        if not isinstance(raw, str):
            raise IntakeValidationError("Invalid value for 'equipment_access': must be text.")
        raw = map_equipment_access(raw)
        case_insensitive_enum = True
    if spec.kind == "enum":
        return _validate_enum(spec, raw, case_insensitive=case_insensitive_enum)
    if spec.kind == "int":
        return _validate_number(spec, raw, integer=True)
    if spec.kind == "float":
        return _validate_number(spec, raw, integer=False)
    return _validate_text(spec, raw)


def legacy_prefill(legacy_state: dict[str, Any] | None) -> dict[str, Any]:
    """Maps unambiguous values from an incomplete legacy three-step intake.

    Deterministic and LLM-free. Only values the legacy graph validated into
    ``profile_data`` are eligible; ambiguous fallbacks (``balanced`` proportions,
    an unstated ``balanced`` rep preference) are intentionally omitted so the new
    flow asks again rather than guessing.
    """
    if not legacy_state:
        return {}
    data = legacy_state.get("profile_data")
    if not isinstance(data, dict):
        return {}
    prefilled: dict[str, Any] = {}
    for name in (
        "gender",
        "age",
        "height_cm",
        "weight_kg",
        "training_age_years",
        "current_goal",
        "long_term_goal",
        "weekly_frequency",
        "equipment_access",
        "injuries_or_limitations",
        "stress_and_sleep",
    ):
        if data.get(name) is None:
            continue
        try:
            prefilled[name] = validate_answer(name, data[name])
        except IntakeValidationError:
            continue
    if data.get("proportions") in _LEGACY_UNAMBIGUOUS_PROPORTIONS:
        prefilled["proportions"] = data["proportions"]
    if data.get("rep_preference") in _LEGACY_UNAMBIGUOUS_REP_PREFERENCES:
        prefilled["rep_preference"] = data["rep_preference"]
    return prefilled


def _initialize_confirmed_from_profile(ledger: Any, profile: dict[str, Any], active: Any) -> None:
    """Synthesizes confirmed intake state for an account with a profile and program."""
    ledger.save_intake_state(
        status=STATUS_CONFIRMED,
        disclosure_acknowledged=1,
        confirmed_at=profile.get("created_at"),
        program_name=active.program_name,
        weekly_frequency=active.weekly_frequency,
    )
    for spec in INTAKE_FIELDS:
        if spec.profile_key not in profile or profile[spec.profile_key] is None:
            continue
        ledger.save_intake_answer(spec.name, profile[spec.profile_key], prefilled=False)


def _initialize_in_progress_from_profile(ledger: Any, profile: dict[str, Any]) -> None:
    """Prefills an editable intake from a profile written before completion.

    A prior intake flow could persist the profile before first-program creation.
    Such an account resumes as in_progress with its answered values prefilled,
    never as confirmed-with-no-program. The disclosure is treated as accepted
    because the profile was saved only after that flow's disclosure step.
    """
    ledger.save_intake_state(status=STATUS_IN_PROGRESS, disclosure_acknowledged=1)
    for spec in INTAKE_FIELDS:
        if spec.profile_key not in profile or profile[spec.profile_key] is None:
            continue
        ledger.save_intake_answer(spec.name, profile[spec.profile_key], prefilled=True)


def ensure_intake(db: Any, ledger_id: str, ledger: Any | None = None) -> None:
    """Creates the structured state on first read/answer, idempotently.

    Order of resolution: an existing structured state wins; otherwise a profile
    plus an active program means the account already onboarded (confirmed, values
    from the profile); a profile with no active program resumes in_progress with
    values prefilled; otherwise an incomplete legacy intake prefills compatible
    fields; otherwise the intake starts empty.

    This is the only write on ``GET /onboarding/intake`` and it is required:
    legacy accounts have no structured row, so the contract must synthesize their
    prefill/confirmed state on first read.
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        if ledger.get_intake_state() is not None:
            return
        profile = ledger.get_player_profile()
        if profile:
            active = ledger.get_active_program()
            if active is not None:
                _initialize_confirmed_from_profile(ledger, profile, active)
            else:
                _initialize_in_progress_from_profile(ledger, profile)
            return
        prefilled = legacy_prefill(ledger.load_onboarding_state())
        ledger.save_intake_state(status=STATUS_IN_PROGRESS)
        for name, value in prefilled.items():
            ledger.save_intake_answer(name, value, prefilled=True)


def build_view(db: Any, ledger_id: str, ledger: Any | None = None) -> dict[str, Any]:
    """The full intake contract: schema, saved answers, prefill markers, progress."""
    with ledger_scope(db, ledger, ledger_id) as ledger:
        ensure_intake(db, ledger_id, ledger=ledger)
        state = ledger.get_intake_state() or {}
        answers = ledger.load_intake_answers()

    fields: list[dict[str, Any]] = []
    for spec in INTAKE_FIELDS:
        entry = answers.get(spec.name)
        fields.append(
            {
                "name": spec.name,
                "type": spec.kind,
                "required": spec.required,
                "allowed_values": list(spec.allowed),
                "minimum": spec.minimum,
                "maximum": spec.maximum,
                "minimum_length": MIN_TEXT_LENGTH if spec.kind == "text" else None,
                "maximum_length": MAX_TEXT_LENGTH if spec.kind == "text" else None,
                "profile_field": spec.profile_key,
                "explanation": spec.explanation,
                "explanation_message": _intake_copy_message(
                    f"intake.{spec.name}.explanation.v1", spec.explanation
                ),
                "hint": spec.hint,
                "hint_message": _intake_copy_message(
                    f"intake.{spec.name}.hint.v1", spec.hint
                ),
                "examples": list(spec.examples),
                "example_messages": [
                    _intake_copy_message(
                        f"intake.{spec.name}.example.{index}.v1", example
                    )
                    for index, example in enumerate(spec.examples, start=1)
                ],
                "option_descriptions": dict(spec.option_descriptions),
                "option_description_messages": {
                    option_value: _intake_copy_message(
                        f"intake.{spec.name}.option.{_intake_option_slug(option_value)}.v1",
                        option_description,
                    )
                    for option_value, option_description in spec.option_descriptions.items()
                },
                "answer": entry["value"] if entry else None,
                "prefilled": bool(entry["prefilled"]) if entry else False,
                "answered": entry is not None,
                "updated_at": entry["updated_at"] if entry else None,
            }
        )

    status = state.get("status", STATUS_IN_PROGRESS)
    program = None
    if status == STATUS_CONFIRMED:
        program_message = state.get("program_message")
        program = {
            "program_name": state.get("program_name"),
            "weekly_frequency": state.get("weekly_frequency"),
            "program_message": program_message,
            "program_message_metadata": _program_message_metadata(program_message),
        }
    return {
        "status": status,
        "profile_rebuild_fields": list(PROFILE_REBUILD_FIELDS),
        "disclosure_acknowledged": bool(state.get("disclosure_acknowledged")),
        "fields": fields,
        "progress": {
            "answered_required": sum(1 for name in REQUIRED_FIELDS if name in answers),
            "required_total": len(REQUIRED_FIELDS),
            "answered": len(answers),
            "total_fields": len(INTAKE_FIELDS),
            "next_unanswered": next((name for name in REQUIRED_FIELDS if name not in answers), None),
        },
        "program": program,
    }


def acknowledge_disclosure(db: Any, ledger_id: str, ledger: Any | None = None) -> dict[str, Any]:
    """Records acknowledgment of the onboarding privacy notice before answers."""
    with ledger_scope(db, ledger, ledger_id) as ledger:
        ensure_intake(db, ledger_id, ledger=ledger)
        ledger.save_intake_state(disclosure_acknowledged=1)
    return build_view(db, ledger_id, ledger=ledger)


def save_answer(
    db: Any,
    ledger_id: str,
    field_name: str,
    raw: Any,
    ledger: Any | None = None,
    *,
    player_account_id: str | None = None,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> dict[str, Any]:
    """Validates and persists one answer; refuses after confirmation.

    Editing an already-answered field overwrites only that field, so earlier
    answers are never lost. The write is idempotent.
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        ensure_intake(db, ledger_id, ledger=ledger)
        state = ledger.get_intake_state() or {}
        if state.get("status") == STATUS_CONFIRMED:
            raise IntakeAlreadyConfirmed(
                "This intake is already confirmed and can no longer be edited."
            )
        if not state.get("disclosure_acknowledged"):
            raise IntakeDisclosureRequired(
                "Acknowledge the onboarding privacy notice before saving answers."
            )
        value = validate_answer(field_name, raw)
        with ledger.ledger_transaction():
            ledger.save_intake_answer(field_name, value, prefilled=False)
            if field_name == "injuries_or_limitations":
                injuries_service.import_legacy_injury_text(
                    db,
                    ledger,
                    injuries_service.LegacyInjuryImport(player_account_id, value, client),
                )
    return build_view(db, ledger_id, ledger=ledger)


def _confirmation_result(state: dict[str, Any]) -> dict[str, Any]:
    program_message = state.get("program_message")
    return {
        "status": STATUS_CONFIRMED,
        "program_name": state.get("program_name"),
        "weekly_frequency": state.get("weekly_frequency"),
        "program_message": program_message,
        "program_message_metadata": _program_message_metadata(program_message),
    }


def confirm_intake(
    db: Any,
    ledger_id: str,
    player_account_id: str | None = None,
    ledger: Any | None = None,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> dict[str, Any]:
    """Writes the confirmed profile and creates the first program, exactly once.

    Concurrency (ADR 021): the single status row is claimed atomically
    (``in_progress`` -> ``confirming``) before any generation, so a second request
    that arrives while generation is in flight is refused 409 instead of
    generating a second program; once confirmed, both replay the stored result.
    Generation reuses ``service.onboarding.complete_onboarding`` and obeys
    program authority (ADR 026). If generation fails, the claim is released back
    to ``in_progress`` and the error re-raised so the player can retry.
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        ensure_intake(db, ledger_id, ledger=ledger)
        state = ledger.get_intake_state() or {}
        if state.get("status") == STATUS_CONFIRMED:
            return _confirmation_result(state)
        if state.get("status") == STATUS_CONFIRMING:
            raise IntakeConfirmInProgress("A program is already being generated for this intake.")
        if not state.get("disclosure_acknowledged"):
            raise IntakeDisclosureRequired(
                "Acknowledge the onboarding privacy notice before creating your program."
            )

        answers = ledger.load_intake_answers()
        missing = [name for name in REQUIRED_FIELDS if name not in answers]
        if missing:
            raise IntakeValidationError(
                "Missing required onboarding answers: " + ", ".join(missing) + "."
            )

        confirmed_instant = datetime.now(UTC)
        confirmed_at = confirmed_instant.isoformat()
        if not ledger.claim_intake_confirmation(confirmed_at):
            # Lost the race: replay if the winner already confirmed, else report busy.
            state = ledger.get_intake_state() or {}
            if state.get("status") == STATUS_CONFIRMED:
                return _confirmation_result(state)
            raise IntakeConfirmInProgress("A program is already being generated for this intake.")

        profile = {FIELD_BY_NAME[name].profile_key: answers[name]["value"] for name in answers}
        with ledger.ledger_transaction():
            ledger.upsert_player_profile_with_weight_history(
                profile, player_local_date(ledger, ledger_id, confirmed_instant).isoformat()
            )
            injuries_service.import_legacy_injury_text(
                db,
                ledger,
                injuries_service.LegacyInjuryImport(
                    player_account_id,
                    profile.get("injuries_or_limitations"),
                    client,
                ),
            )
        if player_account_id:
            evaluate_for_player(db, player_account_id, ledger=ledger)

        try:
            result = onboarding_service.complete_onboarding(
                db,
                ledger_id,
                player_account_id=player_account_id,
                ledger=ledger,
            )
        except BaseException:
            ledger.release_intake_confirmation(datetime.now(UTC).isoformat())
            raise

        program = result.get("program")
        ledger.clear_onboarding_state()

        if program is None:
            ledger.save_intake_state(
                status=STATUS_CONFIRMED,
                confirmed_at=confirmed_at,
                program_message=result.get("program_message"),
            )
            return {
                "status": STATUS_CONFIRMED,
                "program_name": None,
                "weekly_frequency": None,
                "program_message": result.get("program_message"),
                "program_message_metadata": _program_message_metadata(
                    result.get("program_message")
                ),
            }

        ledger.save_intake_state(
            status=STATUS_CONFIRMED,
            confirmed_at=confirmed_at,
            program_name=program.program_name,
            weekly_frequency=program.weekly_frequency,
            program_message=None,
        )
        persisted = ledger.get_active_program()
        if result.get("program_generated") and player_account_id and persisted is not None:
            capture_program_generated(
                ProgramAnalyticsActor(player_account_id, "player"),
                "onboarding",
                persisted,
                client=client,
            )
        return {
            "status": STATUS_CONFIRMED,
            "program_name": program.program_name,
            "weekly_frequency": program.weekly_frequency,
            "program_message": None,
        }
