"""Coach-authored program publication (ticket #26).

A coach with the live capability and an active, owned assignment generates a
program for that player through the normal pipeline, stamped with the coaching
account as provenance (ADR 026). The player's ledger is mounted only after the
assignment gate passes; unknown, ended, and other-coach assignments all deny
with ``None``. Publication is durable — the program is retained, with its
authority, even after the assignment ends.
"""

from datetime import UTC, datetime
from typing import Any

from agent.program_generator import generate_program_pipeline
from service.assignments import authorized_player_ledger


def publish_program(
    db: Any,
    coach_account_id: str,
    assignment_id: Any,
    user_split_override: str | None = None,
    rep_preference_override: str | None = None,
    frequency_override: int | None = None,
) -> Any:
    """Generates and activates a coach-owned program for an assigned player.

    Returns the persisted program (carrying its stable version and provenance),
    or ``None`` when the assignment is not active and owned by this coach.
    """
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        from svc.llm import InferenceScope, run_inference_sync

        _program, _ = run_inference_sync(
            generate_program_pipeline,
            user_split_override=user_split_override,
            rep_preference_override=rep_preference_override,
            frequency_override=frequency_override,
            published_by_coach_account_id=coach_account_id,
            ledger=ledger,
            scope=InferenceScope(
                account_id=coach_account_id, role="coach", purpose="coach_program_publish", store=db
            ),
        )

        published = ledger.get_active_program()
        if published is None:
            raise RuntimeError("Published program is missing from the player ledger after save.")

        db.create_assignment_notice(
            context["player"]["account_id"],
            context["assignment"]["assignment_id"],
            "program_published",
            f"Your coach published program version {published.version}.",
            datetime.now(UTC).isoformat(),
        )
        return published
