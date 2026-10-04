"""Pseudonymous product analytics boundary and PostHog adapter (ADR 040).

Analytics adapter errors are isolated here because observation must never alter
the outcome of an account or onboarding operation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

import httpx
from fastapi import Request

from database.registry.accounts import FIRST_TOUCH_ACQUISITION_FIELDS
from service import acquisition
from utils.model_metering import FINISH_REASONS as AI_FINISH_REASONS

logger = logging.getLogger(__name__)

POSTHOG_EU_HOST = "https://eu.i.posthog.com"
POSTHOG_EU_API_HOST = "https://eu.posthog.com"
PERSON_DELETION_TIMEOUT_SECONDS = 2.0
_EVENT_NAMESPACE = uuid.UUID("a9aa465e-a723-5e59-a850-447d8d73e8fd")
_APP_VERSION = re.compile(
    r"^(?:unknown|(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)$"
)
_ENVIRONMENTS = frozenset({"development", "production", "test"})
_CLIENT_HEADER = re.compile(r"^(android|web)/([0-9][0-9A-Za-z.+_-]{0,31})$")


@dataclass(frozen=True)
class EventContract:
    """One canonical event name, origin, and complete typed property catalogue."""

    origin: str
    properties: Mapping[str, "PropertyType"]


@dataclass(frozen=True)
class PropertyType:
    """A safe value rule shared by event and person-property catalogues."""

    validate: Callable[[Any], bool]
    description: str
    maximum: int | None = None


@dataclass(frozen=True)
class AnalyticsEvent:
    """One committed domain fact to capture; request dimensions are added at capture."""

    account_id: str
    event: str
    domain_key: str
    role: str
    properties: dict[str, Any] | None = None


class PersonDeletionOutcome(str, Enum):
    """Whether the deletion request remains pending or was accepted."""

    PENDING = "pending"
    DELIVERED = "delivered"


@dataclass(frozen=True)
class ClientContext:
    """Client platform header of the HTTP request that caused an event, if any."""

    header: str | None = None


UNKNOWN_CLIENT = ClientContext()


def client_context(request: Request) -> ClientContext:
    """Reads the platform dimensions an HTTP request carries."""
    return ClientContext(request.headers.get("X-MAYOS-Client"))


class AnalyticsSink(Protocol):
    """Provider interface consumed by the analytics boundary."""

    def capture(self, account_id: str, event: str, event_uuid: str, properties: dict[str, Any]) -> None: ...

    def set_person(self, account_id: str, properties: dict[str, Any]) -> None: ...

    def set_person_once(self, account_id: str, properties: dict[str, Any]) -> None: ...

    def person_deletion_configured(self) -> bool: ...

    def delete_person(self, account_id: str) -> PersonDeletionOutcome: ...


def _enum(values: frozenset[str]) -> PropertyType:
    return PropertyType(lambda value: isinstance(value, str) and value in values, "an allowed value")


def _boolean() -> PropertyType:
    return PropertyType(lambda value: type(value) is bool, "a boolean")


def _bounded_int(maximum: int) -> PropertyType:
    return PropertyType(
        lambda value: type(value) is int and 0 <= value <= maximum,
        "a bounded nonnegative integer",
        maximum=maximum,
    )


def _bounded_number(maximum: float) -> PropertyType:
    return PropertyType(
        lambda value: type(value) in {int, float} and 0 <= value <= maximum,
        "a bounded nonnegative number",
        maximum=int(maximum),
    )


def _model_list() -> PropertyType:
    def is_model_list(value: Any) -> bool:
        from utils.model_downloader import configured_model_ids

        configured = configured_model_ids()
        return (
            isinstance(value, list)
            and 1 <= len(value) <= 5
            and all(isinstance(model, str) and (model == "other" or model in configured) for model in value)
            and len(set(value)) == len(value)
        )

    return PropertyType(is_model_list, "a bounded list of configured model ids or other", maximum=5)


def _is_version_label(value: Any) -> bool:
    return isinstance(value, str) and _APP_VERSION.fullmatch(value) is not None


def _version_label() -> PropertyType:
    return PropertyType(_is_version_label, "a version label or unknown")


def _account_id() -> PropertyType:
    def is_account_id(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        try:
            uuid.UUID(value)
        except ValueError:
            return False
        return True

    return PropertyType(is_account_id, "an immutable account UUID")


def _utm_value() -> PropertyType:
    return PropertyType(
        acquisition.is_normalized_utm_label,
        "a normalized UTM label",
        maximum=64,
    )


def _host_value() -> PropertyType:
    return PropertyType(
        acquisition.is_normalized_referrer_host,
        "a hostname",
        maximum=253,
    )


def _acquisition_value(name: str) -> PropertyType:
    if name.startswith("utm_"):
        return _utm_value()
    if name == "referrer_host":
        return _host_value()
    return _account_id()


_PHASES = frozenset({"closed_trial", "public"})


def _onboarding_step() -> PropertyType:
    """Steps are the intake fields plus the disclosure and review screens.

    Resolved on use: the intake module depends on services that capture events.
    """

    def is_step(value: Any) -> bool:
        from service.intake import INTAKE_FIELDS

        steps = {field.name for field in INTAKE_FIELDS} | {"disclosure", "review"}
        return isinstance(value, str) and value in steps

    return PropertyType(is_step, "an onboarding step identifier")


_PROGRAM_TRIGGERS = frozenset(
    {"onboarding", "profile_rebuild", "player_request", "synthesized", "coach_request"}
)
_COACH_ALERT_KINDS = frozenset(
    {
        "missed_expected_days",
        "follow_up_due",
        "profile_change",
        "stall",
        "deload_recommended",
        "performance_regression",
    }
)
_PROGRAM_REQUEST_KINDS = frozenset({"exercise_substitution", "split_change"})
_PROGRAM_REQUEST_OUTCOMES = frozenset({"applied", "declined", "cancelled"})
_PROGRAM_PROVENANCE = frozenset({"generated", "coach_published", "none"})
AI_USE_CASES = frozenset(
    {
        "chat",
        "onboarding",
        "onboarding_complete",
        "program_active",
        "program_generate",
        "profile_rebuild",
        "coach_generate_draft",
        "coach_program_request",
        "coach_assistant",
        "checkpoint_review",
        "other",
    }
)
AI_PLANS = frozenset({"free", "pro", "unknown"})
AI_LIMITS = frozenset({"requests_per_minute", "daily_tokens"})
AI_OUTCOMES = frozenset({"ok", "error", "interrupted"})
WORKOUT_SYNC_FAILURE_REASONS = ("network", "server", "conflict", "rejected")
_DIMENSION_VALUES: dict[str, frozenset[str]] = {
    "role": frozenset({"player", "coach", "unknown"}),
    "platform": frozenset({"android", "web", "unknown"}),
}
PROPERTY_TYPES: dict[str, PropertyType] = {
    "role": _enum(_DIMENSION_VALUES["role"]),
    "platform": _enum(_DIMENSION_VALUES["platform"]),
    "app_version": _version_label(),
    "env": _enum(_ENVIRONMENTS),
    "signup_phase": _enum(_PHASES),
    "invite_used": _boolean(),
    "duration_seconds": _bounded_int(3_155_760_000),
    "time_since_invite_seconds": _bounded_int(31_557_600),
    "prefilled_fields_count": _bounded_int(100),
    "day_count": _bounded_int(100),
    "days_per_week": _bounded_int(7),
    "length_days": _bounded_int(14),
    "set_count": _bounded_int(1000),
    "exercise_count": _bounded_int(100),
    "load_complete_set_count": _bounded_int(1000),
    "reps_complete_set_count": _bounded_int(1000),
    "rir_complete_set_count": _bounded_int(1000),
    "divergence_count": _bounded_int(100),
    "unplanned_exercise_count": _bounded_int(100),
    "captured_offline": _boolean(),
    "sync_delay_seconds": _bounded_int(31_557_600),
    "is_first_workout": _boolean(),
    "program_provenance": _enum(_PROGRAM_PROVENANCE),
    "attempt": _bounded_int(100),
    "sync_failure_reason": _enum(frozenset(WORKOUT_SYNC_FAILURE_REASONS)),
    "trigger": _enum(_PROGRAM_TRIGGERS),
    "first_for_assignment": _boolean(),
    "is_coaching_action": _boolean(),
    "kind": _enum(_PROGRAM_REQUEST_KINDS),
    "outcome": _enum(_PROGRAM_REQUEST_OUTCOMES | AI_OUTCOMES),
    "time_open_seconds": _bounded_int(31_557_600),
    "is_player": _boolean(),
    "is_coach": _boolean(),
    "step": _onboarding_step(),
    "coached": _boolean(),
    "active_roster_size": _bounded_int(200),
    "analytics_opted_out": _boolean(),
    "coach_id": _account_id(),
    "ended_by": _enum(frozenset({"player", "coach", "coach_capability_disabled", "account_deleted"})),
    "reason_code": _enum(
        frozenset(
            {
                "unknown_code",
                "already_redeemed",
                "expired",
                "coach_unavailable",
                "not_a_player",
                "self_assignment",
                "already_assigned",
                "capacity",
                "consent_required",
            }
        )
    ),
    "alert_kind": _enum(_COACH_ALERT_KINDS),
    "use_case": _enum(AI_USE_CASES),
    "plan": _enum(AI_PLANS),
    "models": _model_list(),
    "model_count": _bounded_int(5),
    "input_tokens": _bounded_int(10_000_000),
    "output_tokens": _bounded_int(10_000_000),
    "tokens": _bounded_int(20_000_000),
    "cost_usd": _bounded_number(100_000),
    "estimated": _boolean(),
    "latency_ms": _bounded_int(31_557_600),
    "finish_reason": _enum(AI_FINISH_REASONS),
    "turns_today": _bounded_int(1_000_000),
    "requests_per_minute_limit": _bounded_int(1_000_000),
    "tokens_today": _bounded_int(100_000_000),
    "tokens_daily_limit": _bounded_int(100_000_000),
    "limit": _enum(AI_LIMITS),
}
PROPERTY_TYPES.update({name: _acquisition_value(name) for name in FIRST_TOUCH_ACQUISITION_FIELDS})
_COMMON_PROPERTIES = {name: PROPERTY_TYPES[name] for name in ("role", "platform", "app_version", "env")}
EVENT_CATALOGUE: dict[str, EventContract] = {
    "account_created": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "signup_phase": PROPERTY_TYPES["signup_phase"],
            "invite_used": PROPERTY_TYPES["invite_used"],
        },
    ),
    "onboarding_started": EventContract("server", dict(_COMMON_PROPERTIES)),
    "onboarding_completed": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "duration_seconds": PROPERTY_TYPES["duration_seconds"],
            "prefilled_fields_count": PROPERTY_TYPES["prefilled_fields_count"],
        },
    ),
    "onboarding_step_viewed": EventContract(
        "client",
        {**_COMMON_PROPERTIES, "step": PROPERTY_TYPES["step"]},
    ),
    "coach_capability_granted": EventContract("server", dict(_COMMON_PROPERTIES)),
    "coach_capability_disabled": EventContract("server", dict(_COMMON_PROPERTIES)),
    "assignment_invite_issued": EventContract(
        "server", {**_COMMON_PROPERTIES, "active_roster_size": PROPERTY_TYPES["active_roster_size"]}
    ),
    "assignment_started": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "coach_id": PROPERTY_TYPES["coach_id"],
            "active_roster_size": PROPERTY_TYPES["active_roster_size"],
            "time_since_invite_seconds": PROPERTY_TYPES["time_since_invite_seconds"],
        },
    ),
    "assignment_ended": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "ended_by": PROPERTY_TYPES["ended_by"],
            "duration_seconds": PROPERTY_TYPES["duration_seconds"],
            "active_roster_size": PROPERTY_TYPES["active_roster_size"],
        },
    ),
    "invite_redemption_failed": EventContract(
        "server", {**_COMMON_PROPERTIES, "reason_code": PROPERTY_TYPES["reason_code"]}
    ),
    "program_generated": EventContract(
        "server",
        {**_COMMON_PROPERTIES, "trigger": PROPERTY_TYPES["trigger"], "day_count": PROPERTY_TYPES["day_count"]},
    ),
    "coach_program_published": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "day_count": PROPERTY_TYPES["day_count"],
            "first_for_assignment": PROPERTY_TYPES["first_for_assignment"],
            "is_coaching_action": PROPERTY_TYPES["is_coaching_action"],
        },
    ),
    "program_exercise_swapped": EventContract("server", dict(_COMMON_PROPERTIES)),
    "program_request_created": EventContract(
        "server", {**_COMMON_PROPERTIES, "kind": PROPERTY_TYPES["kind"]}
    ),
    "program_request_resolved": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "outcome": PROPERTY_TYPES["outcome"],
            "time_open_seconds": PROPERTY_TYPES["time_open_seconds"],
            "is_coaching_action": PROPERTY_TYPES["is_coaching_action"],
        },
    ),
    "workout_completed": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "set_count": PROPERTY_TYPES["set_count"],
            "exercise_count": PROPERTY_TYPES["exercise_count"],
            "load_complete_set_count": PROPERTY_TYPES["load_complete_set_count"],
            "reps_complete_set_count": PROPERTY_TYPES["reps_complete_set_count"],
            "rir_complete_set_count": PROPERTY_TYPES["rir_complete_set_count"],
            "divergence_count": PROPERTY_TYPES["divergence_count"],
            "unplanned_exercise_count": PROPERTY_TYPES["unplanned_exercise_count"],
            "captured_offline": PROPERTY_TYPES["captured_offline"],
            "sync_delay_seconds": PROPERTY_TYPES["sync_delay_seconds"],
            "is_first_workout": PROPERTY_TYPES["is_first_workout"],
            "program_provenance": PROPERTY_TYPES["program_provenance"],
            "coached": PROPERTY_TYPES["coached"],
        },
    ),
    "performed_date_corrected": EventContract("server", dict(_COMMON_PROPERTIES)),
    "training_schedule_set": EventContract(
        "server", {**_COMMON_PROPERTIES, "days_per_week": PROPERTY_TYPES["days_per_week"]}
    ),
    "schedule_pause_scheduled": EventContract(
        "server", {**_COMMON_PROPERTIES, "length_days": PROPERTY_TYPES["length_days"]}
    ),
    "coach_alert_created": EventContract(
        "server", {**_COMMON_PROPERTIES, "alert_kind": PROPERTY_TYPES["alert_kind"]}
    ),
    "coach_alerts_viewed": EventContract("server", dict(_COMMON_PROPERTIES)),
    "coach_alert_acknowledged": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "alert_kind": PROPERTY_TYPES["alert_kind"],
            "time_open_seconds": PROPERTY_TYPES["time_open_seconds"],
            "is_coaching_action": PROPERTY_TYPES["is_coaching_action"],
        },
    ),
    "coach_alert_resolved": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "alert_kind": PROPERTY_TYPES["alert_kind"],
            "time_open_seconds": PROPERTY_TYPES["time_open_seconds"],
            "is_coaching_action": PROPERTY_TYPES["is_coaching_action"],
        },
    ),
    "check_in_recorded": EventContract(
        "server", {**_COMMON_PROPERTIES, "is_coaching_action": PROPERTY_TYPES["is_coaching_action"]}
    ),
    "player_history_viewed": EventContract("server", dict(_COMMON_PROPERTIES)),
    "workout_sync_failed": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "sync_failure_reason": PROPERTY_TYPES["sync_failure_reason"],
            "attempt": PROPERTY_TYPES["attempt"],
        },
    ),
    "ai_request_completed": EventContract(
        "server",
        {
            **_COMMON_PROPERTIES,
            "plan": PROPERTY_TYPES["plan"],
            "use_case": PROPERTY_TYPES["use_case"],
            "models": PROPERTY_TYPES["models"],
            "model_count": PROPERTY_TYPES["model_count"],
            "input_tokens": PROPERTY_TYPES["input_tokens"],
            "output_tokens": PROPERTY_TYPES["output_tokens"],
            "tokens": PROPERTY_TYPES["tokens"],
            "cost_usd": PROPERTY_TYPES["cost_usd"],
            "estimated": PROPERTY_TYPES["estimated"],
            "latency_ms": PROPERTY_TYPES["latency_ms"],
            "outcome": PROPERTY_TYPES["outcome"],
            "finish_reason": PROPERTY_TYPES["finish_reason"],
            "turns_today": PROPERTY_TYPES["turns_today"],
            "requests_per_minute_limit": PROPERTY_TYPES["requests_per_minute_limit"],
            "tokens_today": PROPERTY_TYPES["tokens_today"],
            "tokens_daily_limit": PROPERTY_TYPES["tokens_daily_limit"],
        },
    ),
    "ai_request_limited": EventContract(
        "server", {**_COMMON_PROPERTIES, "plan": PROPERTY_TYPES["plan"], "limit": PROPERTY_TYPES["limit"]}
    ),
    "workout_started": EventContract("client", dict(_COMMON_PROPERTIES)),
    "workout_draft_discarded": EventContract("client", dict(_COMMON_PROPERTIES)),
}

PERSON_PROPERTY_CATALOGUE: dict[str, PropertyType] = {
    name: PROPERTY_TYPES[name]
    for name in (
        "is_player",
        "is_coach",
        "coached",
        "active_roster_size",
        "analytics_opted_out",
        "signup_phase",
        *FIRST_TOUCH_ACQUISITION_FIELDS,
    )
}
_MUTABLE_PERSON_PROPERTIES = {
    name: PERSON_PROPERTY_CATALOGUE[name]
    for name in ("is_player", "is_coach", "coached", "active_roster_size", "analytics_opted_out")
}
_SET_ONCE_PERSON_PROPERTIES = {
    name: PERSON_PROPERTY_CATALOGUE[name]
    for name in ("signup_phase", *FIRST_TOUCH_ACQUISITION_FIELDS)
}


class AnalyticsContractError(ValueError):
    """An event or person update breaks the privacy-safe analytics contract."""


class NoOpAnalyticsSink:
    """A sink used when analytics is unconfigured or explicitly disabled."""

    def capture(self, *_args: Any) -> None:
        return None

    def set_person(self, *_args: Any) -> None:
        return None

    def set_person_once(self, *_args: Any) -> None:
        return None

    def person_deletion_configured(self) -> bool:
        return False

    def delete_person(self, *_args: Any) -> PersonDeletionOutcome:
        return PersonDeletionOutcome.PENDING


def _validate_property(name: str, value: Any, property_type: PropertyType) -> None:
    if not property_type.validate(value):
        raise AnalyticsContractError(f"Analytics property {name!r} must be {property_type.description}.")


def validate_event(event: str, properties: dict[str, Any]) -> None:
    """Rejects unknown event contracts, extra/missing properties, and unsafe values."""
    contract = EVENT_CATALOGUE.get(event)
    if contract is None:
        raise AnalyticsContractError(f"Unknown analytics event {event!r}.")
    if contract.origin != "server":
        raise AnalyticsContractError(f"Analytics event {event!r} is not owned by the server.")
    actual = set(properties)
    unknown = actual - set(contract.properties)
    missing = set(contract.properties) - actual
    if unknown:
        raise AnalyticsContractError(f"Unknown properties for analytics event {event!r}: {sorted(unknown)}.")
    if missing:
        raise AnalyticsContractError(f"Missing properties for analytics event {event!r}: {sorted(missing)}.")

    for name, value in properties.items():
        _validate_property(name, value, contract.properties[name])


def _validate_account_id(account_id: str) -> None:
    try:
        uuid.UUID(account_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise AnalyticsContractError("Analytics distinct_id must be an immutable account UUID.") from exc


def _validate_person(properties: dict[str, Any], catalogue: Mapping[str, PropertyType]) -> None:
    unknown = set(properties) - catalogue.keys()
    if unknown:
        raise AnalyticsContractError(f"Unknown analytics person property {sorted(unknown)[0]!r}.")
    for name, value in properties.items():
        _validate_property(name, value, catalogue[name])


def _posthog_person_deletion_url(host: str, project_id: str) -> str | None:
    try:
        parsed_host = httpx.URL(host)
    except httpx.InvalidURL:
        return None
    if (
        parsed_host.scheme != "https"
        or parsed_host.host is None
        or parsed_host.path not in {"", "/"}
        or parsed_host.query
        or parsed_host.fragment
        or re.fullmatch(r"[0-9]+", project_id) is None
    ):
        return None
    return f"{str(parsed_host).rstrip('/')}/api/projects/{project_id}/persons/bulk_delete/"


def _posthog_person_deletion_request(url: str, api_key: str, account_id: str) -> bytes | None:
    payload = {"distinct_ids": [account_id], "delete_events": True, "delete_recordings": False}
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=PERSON_DELETION_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.content
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if 400 <= status < 500:
            logger.error(
                "PostHog person deletion rejected with HTTP %s; verify person:write scope and POSTHOG_PROJECT_ID.",
                status,
            )
        else:
            logger.warning("PostHog person deletion request failed with HTTP %s.", status)
        return None
    except httpx.HTTPError as exc:
        logger.warning("PostHog person deletion request failed (%s).", type(exc).__name__)
        return None


def _posthog_person_deletion_accepted(response_body: bytes | None) -> bool:
    if response_body is None:
        return False
    if not response_body:
        return True
    try:
        response = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("PostHog person deletion returned an unreadable response.")
        return False
    if not isinstance(response, dict) or response.get("deletion_errors"):
        return False
    found = response.get("persons_found")
    queued = response.get("persons_queued_for_deletion")
    return type(found) is int and (found == 0 or (found > 0 and type(queued) is int and queued == found))


def deterministic_event_uuid(event: str, domain_key: str) -> str:
    """Returns the stable PostHog event UUID for one domain event key."""
    return str(uuid.uuid5(_EVENT_NAMESPACE, f"mayos:{event}:{domain_key}"))


def release_phase() -> str:
    """Reads the current cohort phase, falling back to the closed-trial phase."""
    phase = os.getenv("MAYOS_RELEASE_PHASE", "closed_trial").strip()
    if phase in _PHASES:
        return phase
    logger.warning("Ignoring unrecognized MAYOS_RELEASE_PHASE; using closed_trial.")
    return "closed_trial"


def deployment_environment() -> str:
    """Returns the configured environment label, defaulting to development."""
    configured = os.getenv("MAYOS_ENV", "").strip().lower()
    if configured in _ENVIRONMENTS:
        return configured
    return "development"


def resolve_dimensions(client_header: str | None, *, role: str) -> dict[str, str]:
    """Resolves the safe request dimensions in one place."""
    platform = "unknown"
    app_version = "unknown"
    if client_header:
        match = _CLIENT_HEADER.fullmatch(client_header.strip())
        if match:
            platform, app_version = match.groups()
            if not PROPERTY_TYPES["app_version"].validate(app_version):
                app_version = "unknown"
    return {
        "role": role if role in _DIMENSION_VALUES["role"] else "unknown",
        "platform": platform,
        "app_version": app_version,
        "env": deployment_environment(),
    }


class RecordingAnalyticsSink:
    """Strict in-memory provider replacement for API tests and later tickets."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.people: dict[str, dict[str, Any]] = {}
        self.people_updates: list[dict[str, Any]] = []
        self.people_set_once: dict[str, dict[str, Any]] = {}
        self.deleted_people: set[str] = set()

    def capture(self, account_id: str, event: str, event_uuid: str, properties: dict[str, Any]) -> None:
        _validate_account_id(account_id)
        _validate_account_id(event_uuid)
        validate_event(event, properties)
        self.events.append(
            {"distinct_id": account_id, "event": event, "uuid": event_uuid, "properties": dict(properties)}
        )

    def set_person(self, account_id: str, properties: dict[str, Any]) -> None:
        _validate_account_id(account_id)
        _validate_person(properties, _MUTABLE_PERSON_PROPERTIES)
        self.people_updates.append(
            {"distinct_id": account_id, "properties": dict(properties), "operation": "set"}
        )
        self.people.setdefault(account_id, {}).update(properties)

    def set_person_once(self, account_id: str, properties: dict[str, Any]) -> None:
        _validate_account_id(account_id)
        _validate_person(properties, _SET_ONCE_PERSON_PROPERTIES)
        self.people_updates.append(
            {"distinct_id": account_id, "properties": dict(properties), "operation": "set_once"}
        )
        current = self.people_set_once.setdefault(account_id, {})
        for name, value in properties.items():
            current.setdefault(name, value)

    def person_deletion_configured(self) -> bool:
        return True

    def delete_person(self, account_id: str) -> PersonDeletionOutcome:
        _validate_account_id(account_id)
        self.people.pop(account_id, None)
        self.people_set_once.pop(account_id, None)
        self.deleted_people.add(account_id)
        return PersonDeletionOutcome.DELIVERED


class PostHogAnalyticsSink:
    """PostHog EU cloud adapter. Events use the SDK queue; deletion awaits API acceptance."""

    def __init__(self, api_key: str, host: str | None = None) -> None:
        from posthog import Posthog

        self.client = Posthog(
            api_key,
            host=(host or POSTHOG_EU_HOST),
            disable_geoip=True,
            enable_exception_autocapture=False,
            log_captured_exceptions=False,
            sync_mode=False,
        )
        self.person_api_key = os.getenv("POSTHOG_PERSONAL_API_KEY", "").strip()
        self.project_id = os.getenv("POSTHOG_PROJECT_ID", "").strip()
        self.person_api_host = (
            os.getenv("POSTHOG_API_HOST", "").strip().rstrip("/") or POSTHOG_EU_API_HOST
        )

    @staticmethod
    def _drop_contract_error(error: AnalyticsContractError, event: str) -> None:
        safe_event = event if event in EVENT_CATALOGUE else "unknown"
        logger.warning(
            "Dropping invalid analytics payload for %s (%s).", safe_event, type(error).__name__
        )

    def capture(self, account_id: str, event: str, event_uuid: str, properties: dict[str, Any]) -> None:
        try:
            _validate_account_id(account_id)
            _validate_account_id(event_uuid)
            validate_event(event, properties)
        except AnalyticsContractError as exc:
            self._drop_contract_error(exc, event)
            return
        self.client.capture(
            event,
            distinct_id=account_id,
            properties=properties,
            uuid=event_uuid,
            disable_geoip=True,
        )

    def set_person(self, account_id: str, properties: dict[str, Any]) -> None:
        try:
            _validate_account_id(account_id)
            _validate_person(properties, _MUTABLE_PERSON_PROPERTIES)
        except AnalyticsContractError as exc:
            self._drop_contract_error(exc, "person_set")
            return
        self.client.set(distinct_id=account_id, properties=properties, disable_geoip=True)

    def set_person_once(self, account_id: str, properties: dict[str, Any]) -> None:
        try:
            _validate_account_id(account_id)
            _validate_person(properties, _SET_ONCE_PERSON_PROPERTIES)
        except AnalyticsContractError as exc:
            self._drop_contract_error(exc, "person_set_once")
            return
        self.client.set_once(distinct_id=account_id, properties=properties, disable_geoip=True)

    def person_deletion_configured(self) -> bool:
        return bool(
            self.person_api_key
            and self.project_id
            and _posthog_person_deletion_url(self.person_api_host, self.project_id)
        )

    def delete_person(self, account_id: str) -> PersonDeletionOutcome:
        try:
            _validate_account_id(account_id)
        except AnalyticsContractError as exc:
            self._drop_contract_error(exc, "person_delete")
            return PersonDeletionOutcome.PENDING
        url = _posthog_person_deletion_url(self.person_api_host, self.project_id)
        if not self.person_api_key or url is None:
            return PersonDeletionOutcome.PENDING
        accepted = _posthog_person_deletion_accepted(
            _posthog_person_deletion_request(url, self.person_api_key, account_id)
        )
        return PersonDeletionOutcome.DELIVERED if accepted else PersonDeletionOutcome.PENDING


def create_sink_from_environment() -> NoOpAnalyticsSink | PostHogAnalyticsSink:
    """Builds PostHog only with a key and outside test mode."""
    api_key = os.getenv("POSTHOG_API_KEY", "").strip()
    if os.getenv("TESTING") == "1" or not api_key:
        return NoOpAnalyticsSink()
    return PostHogAnalyticsSink(api_key, os.getenv("POSTHOG_HOST", "").strip() or None)


_sink: AnalyticsSink = NoOpAnalyticsSink()
_sink_is_override = False
_analytics_preference_reader: Callable[[str], bool] | None = None
_preference_reader_is_override = False


def register_analytics_preference_reader(reader: Callable[[str], bool] | None) -> None:
    """Registers the registry lookup used to gate account-scoped sends.

    Analytics stays a leaf module: the application supplies the registry seam
    rather than importing database code here. A missing or failing reader
    suppresses sends. A reader installed with
    ``override_analytics_preference_reader`` is kept.
    """
    global _analytics_preference_reader
    if not _preference_reader_is_override:
        _analytics_preference_reader = reader


def override_analytics_preference_reader(reader: Callable[[str], bool] | None) -> None:
    """Replaces the preference lookup regardless of app startup; ``None`` clears the override."""
    global _analytics_preference_reader, _preference_reader_is_override
    _analytics_preference_reader = reader
    _preference_reader_is_override = reader is not None


def _account_allows_analytics(account_id: str) -> bool:
    reader = _analytics_preference_reader
    if reader is None:
        return False
    try:
        return reader(account_id) is True
    except Exception as exc:
        logger.warning(
            "Suppressing product analytics because the account preference could not be read (%s).",
            type(exc).__name__,
        )
        return False


def _install_sink(sink: AnalyticsSink) -> None:
    global _sink
    _sink = sink


def set_sink(sink: AnalyticsSink | None) -> None:
    """Replaces the active provider; passing ``None`` restores the no-op."""
    global _sink_is_override
    _install_sink(sink if sink is not None else NoOpAnalyticsSink())
    _sink_is_override = sink is not None


def register_configured_sink() -> None:
    """Registers the configured sink at app creation without replacing test overrides."""
    if not _sink_is_override:
        _install_sink(create_sink_from_environment())


def _observe(action: Callable[[], Any], failure: str) -> Any | None:
    """Runs one sink call so that a provider failure never reaches the operation.

    Contract violations still propagate: only the strict test sink raises them,
    while the production adapter drops and logs invalid payloads itself.
    """
    try:
        return action()
    except AnalyticsContractError:
        raise
    except Exception:
        logger.exception("Product analytics %s failed; the operation continues.", failure)
        return None


def capture(event: AnalyticsEvent, client: ClientContext = UNKNOWN_CLIENT) -> None:
    """Captures one server event with safe dimensions and a deterministic UUID."""
    if not _account_allows_analytics(event.account_id):
        return
    payload = {**resolve_dimensions(client.header, role=event.role), **(event.properties or {})}
    _observe(
        lambda: _sink.capture(
            event.account_id, event.event, deterministic_event_uuid(event.event, event.domain_key), payload
        ),
        f"capture of {event.event}",
    )


def capture_for_request(request: Request, event: AnalyticsEvent) -> None:
    """Captures using the safe client dimensions carried by this request."""
    capture(event, client_context(request))


def set_person(account_id: str, properties: dict[str, Any]) -> None:
    """Sets mutable allowlisted person properties without affecting the request."""
    if not _account_allows_analytics(account_id):
        return
    _observe(lambda: _sink.set_person(account_id, properties), "person update")


def record_opt_out_change(account_id: str, opted_out: bool) -> None:
    """Records the committed analytics choice through the opt-out gate once."""
    _observe(
        lambda: _sink.set_person(account_id, {"analytics_opted_out": opted_out}),
        "analytics preference update",
    )


def set_person_once(account_id: str, properties: dict[str, Any]) -> None:
    """Sets allowlisted person properties once without affecting the request."""
    if not _account_allows_analytics(account_id):
        return
    _observe(lambda: _sink.set_person_once(account_id, properties), "set-once update")


def person_deletion_configured() -> bool:
    """Reports whether the active sink can make a person-deletion request."""
    configured = getattr(_sink, "person_deletion_configured", None)
    try:
        return configured() if callable(configured) else not isinstance(_sink, NoOpAnalyticsSink)
    except Exception as exc:
        logger.warning("Person deletion is unavailable (%s).", type(exc).__name__)
        return False


def delete_person(account_id: str) -> PersonDeletionOutcome:
    """Requests best-effort deletion of one PostHog person."""
    if not person_deletion_configured():
        return PersonDeletionOutcome.PENDING
    try:
        outcome = _sink.delete_person(account_id)
    except AnalyticsContractError:
        raise
    except Exception:
        logger.exception("Product analytics person deletion failed; the operation continues.")
        return PersonDeletionOutcome.PENDING
    if not isinstance(outcome, PersonDeletionOutcome):
        logger.error("Analytics sink returned an invalid person-deletion outcome.")
        return PersonDeletionOutcome.PENDING
    return outcome
