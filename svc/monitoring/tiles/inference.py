"""Inference latency and outcomes, independent of product analytics consent."""

from collections import defaultdict
from typing import Any

from service.inference_metrics import INFERENCE_PURPOSES, set_recorder
from svc.monitoring.measurements import HourlyMeasurements
from svc.monitoring.runtime import MonitoringView
from svc.monitoring.tiles.api import _percentile_cells

PURPOSE_LABELS = {
    "chat": "Player chat",
    "onboarding": "Onboarding",
    "onboarding_complete": "Onboarding completion",
    "program_active": "Active Training program",
    "program_generate": "Training program generation",
    "profile_rebuild": "Training profile rebuild",
    "coach_generate_draft": "Coach Program draft",
    "coach_program_import": "Coach Program import",
    "coach_program_request": "Coach Program request",
    "coach_assistant": "Coach AI",
    "coach_roster_assistant": "Roster briefing",
    "checkpoint_review": "Checkpoint review",
    "other": "Other",
}
FAILED_OUTCOMES = frozenset({"error", "timeout"})


def _purpose_row(purpose: str, rows: list[dict[str, Any]]) -> str:
    turns = [row for row in rows if row["metric"] == "latency"]
    first_tokens = [row for row in rows if row["metric"] == "ttft"]
    count = sum(row["count"] for row in turns)
    failed = sum(row["count"] for row in turns if row["dimensions"]["outcome"] in FAILED_OUTCOMES)
    timeouts = sum(row["count"] for row in turns if row["dimensions"]["outcome"] == "timeout")
    failure_rate = f"{failed / count:.2%}" if count else "No samples"
    timeout_rate = f"{timeouts / count:.2%}" if count else "No samples"
    return (
        f'<tr><th scope="row">{PURPOSE_LABELS[purpose]}</th><td>{count:,}</td>'
        + _percentile_cells(turns) + _percentile_cells(first_tokens)
        + f'<td>{failure_rate}</td><td>{timeout_rate}</td></tr>'
    )


class InferenceProvider:
    key = "inference"

    def __init__(self) -> None:
        self.measurements = HourlyMeasurements()

    def record(self, purpose: str, outcome: str, latency_ms: float, ttft_ms: float | None) -> None:
        dimensions = {"purpose": purpose, "outcome": outcome}
        self.measurements.observe("latency", latency_ms, dimensions)
        if ttft_ms is not None:
            self.measurements.observe("ttft", ttft_ms, dimensions)

    def sample(self) -> None:
        pass  # Turns record their completion; no periodic sampling is needed.

    def render(self, view: MonitoringView) -> str:
        purposes: dict[str, list] = defaultdict(list)
        for row in view.rows:
            purpose = row["dimensions"]["purpose"]
            purposes[purpose if purpose in INFERENCE_PURPOSES else "other"].append(row)
        body = "".join(_purpose_row(purpose, purposes[purpose]) for purpose in PURPOSE_LABELS if purpose in purposes)
        return (
            '<section class="health-panel monitoring-tile" id="inference-latency"><h2>Inference latency</h2>'
            '<p>Includes Players who opted out of analytics. Latency reuses the complete inference turn timing. '
            'p50, p95 and p99 are estimates: the enclosing latency bucket upper bound; overflow is a lower bound. '
            'Time to first token (TTFT) covers the first model stream, including tool-call chunks. '
            'Non-streaming turns and streams with no first token have no TTFT sample.</p>'
            '<p>Failure rate includes errors and timeouts. Timeout rate is the timeout subset. '
            'Both use all turns as the denominator, including interrupted and truncated turns.</p>'
            '<div class="table-scroll"><table><thead><tr><th>Purpose</th><th>Turns</th>'
            '<th>Latency p50</th><th>Latency p95</th><th>Latency p99</th>'
            '<th>TTFT p50</th><th>TTFT p95</th><th>TTFT p99</th>'
            '<th>Failure rate</th><th>Timeout rate</th></tr></thead><tbody>'
            + (body or '<tr><td colspan="10">No inference turns recorded yet.</td></tr>')
            + '</tbody></table></div></section>'
        )


def create_provider(app: Any) -> InferenceProvider:
    provider = InferenceProvider()
    set_recorder(provider.record)
    return provider
