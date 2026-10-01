"""Structured, resumable player onboarding intake (ADR 021).

The module is the single source of truth for the named onboarding decisions the
domain supports: each field's name, type, allowed values/range, required/optional
status, the profile column it maps to, and any explanation shown to the player.
Validation, per-answer persistence, resume/progress, legacy prefill, the
hosted-processing disclosure gate, and confirmation into the existing profile +
first-program path all live here.

Two disclosures are deliberately made explicit because the program code, not
guesswork, defines them:

* The male/female specialization is required and does change the automatic
  split: this flow collects no custom split, so generation uses the
  deterministic default from ``agent.program_blueprints.DEFAULT_SPLIT_BY_FREQUENCY``
  (via ``agent.program_rules.get_default_split``), which routes female to the
  glute/lower-body-biased family and male to the standard family.
* Relative leg/torso proportion is coaching context only (ADR 011) and is never
  read by program generation; it changes neither split nor volume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from service import onboarding as onboarding_service
from service.profile import PROFILE_REBUILD_FIELDS
from service._base import ledger_scope
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

#: The current training effect of the required male/female specialization.
#: Derived from `agent.program_blueprints.DEFAULT_SPLIT_BY_FREQUENCY` /
#: `agent.program_rules.get_default_split`, not from any invented rule. This flow
#: collects no custom split preference, so the gender-selected default family is
#: the whole split effect for the intake path.
SPECIALIZATION_EXPLANATION = (
    "Your specialization is required. It sets the default training split we "
    "build for you: female trainees get glute- and lower-body-focused splits, "
    "male trainees get our standard balanced splits, and your weekly frequency "
    "decides the exact layout."
)

PROPORTIONS_EXPLANATION = (
    "Relative leg and torso length is coaching context only. It does not change "
    "exercise selection, program structure, or training volume."
)

#: Per-value split-family effect of the male/female choice. Derived directly from
#: ``agent.program_blueprints.DEFAULT_SPLIT_BY_FREQUENCY`` (via
#: ``agent.program_rules.get_default_split``): gender picks the default split
#: family for the chosen weekly frequency.
SPECIALIZATION_OPTION_DESCRIPTIONS: dict[str, str] = {
    "male": (
        "Balanced upper- and lower-body training by frequency: full body at "
        "1-3 days, upper/lower at 4 days, Arnold-style at 5 days."
    ),
    "female": (
        "Glute- and lower-body-focused by frequency: glute-specialised full "
        "body at 1-3 days, lower-body (glute bias) and upper body + core at "
        "4-5 days."
    ),
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
    """Answers were submitted before the hosted-processing disclosure -> HTTP 403."""


class IntakeAlreadyConfirmed(IntakeError):
    """The intake can no longer be edited because it is confirmed -> HTTP 409."""


class IntakeConfirmInProgress(IntakeError):
    """Another confirmation owns the claim; a concurrent caller gets HTTP 409."""


class StructuredIntakeActive(IntakeError):
    """Legacy three-step routes are refused while a structured intake exists -> HTTP 409."""


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
    IntakeField("weight_kg", "float", True, "weight_kg", minimum=30, maximum=250),
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

    The legacy graph persists the profile at step 3, but the first program is
    only created when ``/onboarding/complete`` runs. An account with a profile
    and no active program must resume as in_progress with the answered values
    prefilled, never be synthesized as confirmed-with-no-program. The hosted
    disclosure is treated as already accepted because a profile can only exist
    after the player completed the legacy intake, so confirming can generate.
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
    from the profile); a profile with no active program (the graph wrote it but
    ``/complete`` never ran) resumes in_progress with values prefilled; otherwise
    an incomplete legacy three-step intake prefills the compatible fields;
    otherwise the intake starts empty.

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


def structured_intake_active(db: Any, ledger_id: str, ledger: Any | None = None) -> bool:
    """True when a structured intake row exists in any in-progress/confirmed status.

    Accounts with no structured row keep the legacy three-step routes unchanged
    (backward compatibility for the current client until #51 ships).
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        state = ledger.get_intake_state()
    if state is None:
        return False
    return state.get("status") in {STATUS_IN_PROGRESS, STATUS_CONFIRMING, STATUS_CONFIRMED}


def record_legacy_completion(
    db: Any, ledger_id: str, program: Any, program_message: str | None, ledger: Any | None = None
) -> None:
    """Marks an existing structured intake confirmed when legacy ``/complete`` runs.

    Stores the same program result the structured confirm stores, so later answer
    edits are refused 409 and ``POST /intake/confirm`` replays instead of creating
    a second program.
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        if ledger.get_intake_state() is None:
            return
        ledger.save_intake_state(
            status=STATUS_CONFIRMED,
            confirmed_at=datetime.now(UTC).isoformat(),
            program_name=program.program_name if program is not None else None,
            weekly_frequency=program.weekly_frequency if program is not None else None,
            program_message=program_message,
        )


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
                "hint": spec.hint,
                "examples": list(spec.examples),
                "option_descriptions": dict(spec.option_descriptions),
                "answer": entry["value"] if entry else None,
                "prefilled": bool(entry["prefilled"]) if entry else False,
                "answered": entry is not None,
                "updated_at": entry["updated_at"] if entry else None,
            }
        )

    status = state.get("status", STATUS_IN_PROGRESS)
    program = None
    if status == STATUS_CONFIRMED:
        program = {
            "program_name": state.get("program_name"),
            "weekly_frequency": state.get("weekly_frequency"),
            "program_message": state.get("program_message"),
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
    """Records that the hosted-processing disclosure was accepted before answers."""
    with ledger_scope(db, ledger, ledger_id) as ledger:
        ensure_intake(db, ledger_id, ledger=ledger)
        ledger.save_intake_state(disclosure_acknowledged=1)
    return build_view(db, ledger_id, ledger=ledger)


def save_answer(
    db: Any, ledger_id: str, field_name: str, raw: Any, ledger: Any | None = None
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
                "Acknowledge the hosted-processing disclosure before saving onboarding answers."
            )
        value = validate_answer(field_name, raw)
        ledger.save_intake_answer(field_name, value, prefilled=False)
    return build_view(db, ledger_id, ledger=ledger)


def _confirmation_result(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": STATUS_CONFIRMED,
        "program_name": state.get("program_name"),
        "weekly_frequency": state.get("weekly_frequency"),
        "program_message": state.get("program_message"),
    }


def confirm_intake(
    db: Any, ledger_id: str, player_account_id: str | None = None, ledger: Any | None = None
) -> dict[str, Any]:
    """Writes the confirmed profile and creates the first program, exactly once.

    Concurrency (ADR 021): the single status row is claimed atomically
    (``in_progress`` -> ``confirming``) before any generation, so a second request
    that arrives while generation is in flight is refused 409 instead of
    generating a second program; once confirmed, both replay the stored result.
    Generation reuses ``service.onboarding.complete_onboarding`` so it stays
    metered/admitted (ADR 038) and obeys program authority (ADR 026). If
    generation fails (including a model-limit 429), the claim is released back to
    ``in_progress`` and the error re-raised so the player can retry.
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
                "Acknowledge the hosted-processing disclosure before creating your program."
            )

        answers = ledger.load_intake_answers()
        missing = [name for name in REQUIRED_FIELDS if name not in answers]
        if missing:
            raise IntakeValidationError(
                "Missing required onboarding answers: " + ", ".join(missing) + "."
            )

        confirmed_at = datetime.now(UTC).isoformat()
        if not ledger.claim_intake_confirmation(confirmed_at):
            # Lost the race: replay if the winner already confirmed, else report busy.
            state = ledger.get_intake_state() or {}
            if state.get("status") == STATUS_CONFIRMED:
                return _confirmation_result(state)
            raise IntakeConfirmInProgress("A program is already being generated for this intake.")

        profile = {FIELD_BY_NAME[name].profile_key: answers[name]["value"] for name in answers}
        ledger.upsert_player_profile(profile)

        try:
            result = onboarding_service.complete_onboarding(
                db, ledger_id, {}, player_account_id=player_account_id, ledger=ledger
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
            }

        ledger.save_intake_state(
            status=STATUS_CONFIRMED,
            confirmed_at=confirmed_at,
            program_name=program.program_name,
            weekly_frequency=program.weekly_frequency,
            program_message=None,
        )
        return {
            "status": STATUS_CONFIRMED,
            "program_name": program.program_name,
            "weekly_frequency": program.weekly_frequency,
            "program_message": None,
        }
