"""Pseudonymous product analytics boundary and PostHog adapter (ADR 040).

Analytics adapter errors are isolated here because observation must never alter
the outcome of an account or onboarding operation.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request

from service.intake import INTAKE_FIELDS

logger = logging.getLogger(__name__)

POSTHOG_EU_HOST = "https://eu.i.posthog.com"
_EVENT_NAMESPACE = uuid.UUID("a9aa465e-a723-5e59-a850-447d8d73e8fd")
_APP_VERSION = re.compile(r"^(?:unknown|[0-9]{1,3}(?:\.[0-9A-Za-z_-]{1,16}){0,3}(?:\+[0-9A-Za-z.-]{1,12})?)$")
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


@dataclass(frozen=True)
class AnalyticsEvent:
    """One committed domain fact to capture; request dimensions are added at capture."""

    account_id: str
    event: str
    domain_key: str
    role: str
    properties: dict[str, Any] | None = None


class AnalyticsSink(Protocol):
    """Provider interface consumed by the analytics boundary."""

    def capture(self, account_id: str, event: str, event_uuid: str, properties: dict[str, Any]) -> None: ...

    def set_person(self, account_id: str, properties: dict[str, Any]) -> None: ...

    def set_person_once(self, account_id: str, properties: dict[str, Any]) -> None: ...

    def delete_person(self, account_id: str) -> None: ...


def _enum(values: frozenset[str]) -> PropertyType:
    return PropertyType(lambda value: isinstance(value, str) and value in values, "an allowed value")


def _boolean() -> PropertyType:
    return PropertyType(lambda value: type(value) is bool, "a boolean")


def _bounded_int(maximum: int) -> PropertyType:
    return PropertyType(lambda value: type(value) is int and 0 <= value <= maximum, "a bounded nonnegative integer")


def _version_label() -> PropertyType:
    return PropertyType(
        lambda value: isinstance(value, str) and _APP_VERSION.fullmatch(value) is not None,
        "a version label or unknown",
    )


_PHASES = frozenset({"closed_trial", "public"})
_ONBOARDING_STEPS = frozenset(field.name for field in INTAKE_FIELDS) | {
    "disclosure",
    "review",
}
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
    "duration_seconds": _bounded_int(31_557_600),
    "prefilled_fields_count": _bounded_int(100),
    "is_player": _boolean(),
    "is_coach": _boolean(),
    "step": _enum(_ONBOARDING_STEPS),
}
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
}

PERSON_PROPERTY_CATALOGUE: dict[str, PropertyType] = {
    name: PROPERTY_TYPES[name] for name in ("is_player", "is_coach", "signup_phase")
}
_MUTABLE_PERSON_PROPERTIES = {name: PERSON_PROPERTY_CATALOGUE[name] for name in ("is_player", "is_coach")}
_SET_ONCE_PERSON_PROPERTIES = {"signup_phase": PERSON_PROPERTY_CATALOGUE["signup_phase"]}


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

    def delete_person(self, *_args: Any) -> None:
        return None


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
        self.people_set_once: dict[str, dict[str, Any]] = {}
        self.deleted_people: set[str] = set()
        self._event_ids: set[str] = set()

    def capture(self, account_id: str, event: str, event_uuid: str, properties: dict[str, Any]) -> None:
        _validate_account_id(account_id)
        _validate_account_id(event_uuid)
        validate_event(event, properties)
        if event_uuid in self._event_ids:
            return
        self._event_ids.add(event_uuid)
        self.events.append(
            {"distinct_id": account_id, "event": event, "uuid": event_uuid, "properties": dict(properties)}
        )

    def set_person(self, account_id: str, properties: dict[str, Any]) -> None:
        _validate_account_id(account_id)
        _validate_person(properties, _MUTABLE_PERSON_PROPERTIES)
        self.people.setdefault(account_id, {}).update(properties)

    def set_person_once(self, account_id: str, properties: dict[str, Any]) -> None:
        _validate_account_id(account_id)
        _validate_person(properties, _SET_ONCE_PERSON_PROPERTIES)
        current = self.people_set_once.setdefault(account_id, {})
        for name, value in properties.items():
            current.setdefault(name, value)

    def delete_person(self, account_id: str) -> None:
        _validate_account_id(account_id)
        self.people.pop(account_id, None)
        self.people_set_once.pop(account_id, None)
        self.deleted_people.add(account_id)


class PostHogAnalyticsSink:
    """PostHog EU cloud adapter. SDK capture uses its background queue."""

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

    def delete_person(self, account_id: str) -> None:
        try:
            _validate_account_id(account_id)
        except AnalyticsContractError as exc:
            self._drop_contract_error(exc, "person_delete")
            return
        self.client.capture(
            "$delete",
            distinct_id=account_id,
            properties={"$delete_person_profile": True},
            uuid=deterministic_event_uuid("person_deleted", account_id),
            disable_geoip=True,
        )


def create_sink_from_environment() -> NoOpAnalyticsSink | PostHogAnalyticsSink:
    """Builds PostHog only with a key and outside test mode."""
    api_key = os.getenv("POSTHOG_API_KEY", "").strip()
    if os.getenv("TESTING") == "1" or not api_key:
        return NoOpAnalyticsSink()
    return PostHogAnalyticsSink(api_key, os.getenv("POSTHOG_HOST", "").strip() or None)


_sink: AnalyticsSink = NoOpAnalyticsSink()
_sink_is_override = False


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


def _observe(action: Callable[[], None], failure: str) -> None:
    """Runs one sink call so that a provider failure never reaches the operation.

    Contract violations still propagate: only the strict test sink raises them,
    while the production adapter drops and logs invalid payloads itself.
    """
    try:
        action()
    except AnalyticsContractError:
        raise
    except Exception:
        logger.exception("Product analytics %s failed; the operation continues.", failure)


def capture(event: AnalyticsEvent, client_header: str | None = None) -> None:
    """Captures one server event with safe dimensions and a deterministic UUID."""
    payload = {**resolve_dimensions(client_header, role=event.role), **(event.properties or {})}
    _observe(
        lambda: _sink.capture(
            event.account_id, event.event, deterministic_event_uuid(event.event, event.domain_key), payload
        ),
        f"capture of {event.event}",
    )


def capture_for_request(request: Request, event: AnalyticsEvent) -> None:
    """Captures one server event with the platform dimensions of an HTTP request."""
    capture(event, request.headers.get("X-MAYOS-Client"))


def set_person(account_id: str, properties: dict[str, Any]) -> None:
    """Sets mutable allowlisted person properties without affecting the request."""
    _observe(lambda: _sink.set_person(account_id, properties), "person update")


def set_person_once(account_id: str, properties: dict[str, Any]) -> None:
    """Sets allowlisted person properties once without affecting the request."""
    _observe(lambda: _sink.set_person_once(account_id, properties), "set-once update")


def delete_person(account_id: str) -> None:
    """Requests best-effort deletion of one PostHog person."""
    _observe(lambda: _sink.delete_person(account_id), "person deletion")
