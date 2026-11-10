"""Low-cardinality aggregates for authenticated client transport failures."""

import re
import warnings
from typing import Any

from svc.monitoring.measurements import HourlyMeasurements
from svc.schemas import ClientConnectionFailureIn

_ROUTE_PARAMETER_SEGMENT = re.compile(r"\{[^{}]+\}")


def _path_segments(route_path: str) -> tuple[str, ...] | None:
    if not route_path.startswith("/") or "?" in route_path or "#" in route_path:
        return None
    if route_path == "/":
        return ()
    segments = tuple(route_path[1:].split("/"))
    return segments if segments[0] and all(segments[:-1]) else None


def _canonical_route_template(route_path: str) -> str | None:
    segments = _path_segments(route_path)
    if segments is None:
        return None
    canonical = (
        "{id}" if _ROUTE_PARAMETER_SEGMENT.fullmatch(segment) else segment
        for segment in segments
    )
    return "/" + "/".join(canonical) if segments else "/"


def safe_route_template(
    route_path: str,
    registered_templates: frozenset[str],
) -> str:
    """Return a registered route template only when every submitted segment matches."""
    segments = _path_segments(route_path)
    if segments is None:
        return "/unknown"
    for template in sorted(registered_templates):
        template_segments = _path_segments(template)
        if template_segments is None or len(segments) != len(template_segments):
            continue
        if all(
            _ROUTE_PARAMETER_SEGMENT.fullmatch(template_segment)
            or segment == template_segment
            for segment, template_segment in zip(segments, template_segments)
        ):
            return template
    return "/unknown"


def registered_route_templates(app: Any) -> frozenset[str]:
    """Every API path template, read from the OpenAPI schema.

    FastAPI includes routers lazily, so ``app.routes`` no longer lists their
    paths; the schema is the public, complete list. Routes hidden from the
    schema aggregate under ``/unknown``.
    """
    with warnings.catch_warnings():
        # GET+HEAD health routes share an operation id; harmless for a path list.
        warnings.filterwarnings("ignore", message="Duplicate Operation ID", category=UserWarning)
        paths = app.openapi().get("paths", {})
    return frozenset(
        template
        for route_path in paths
        if (template := _canonical_route_template(route_path)) is not None
    )


class ConnectionFailureMetrics:
    """In-process hourly counts, with no per-event or account data."""

    def __init__(self) -> None:
        self.measurements = HourlyMeasurements()

    def record(
        self,
        failure: ClientConnectionFailureIn,
        allowed_routes: frozenset[str],
    ) -> None:
        route = safe_route_template(failure.route_template, allowed_routes)
        self.measurements.observe(
            "client_connection_failures",
            1,
            {
                "failure_type": failure.failure_type,
                "platform": failure.platform,
                "route": route,
            },
            at=failure.occurred_at,
        )
