"""Assignment invite and lifecycle routes (ticket #24).

Three route groups share this module:

* ``/coach/assignments`` — coach issue, notices, roster identity, and revoke. Every
  route requires the live coach capability, which is checked from the durable
  registry before any ledger is mounted.
* ``/coach/program-requests`` — the cross-roster request queue (ticket #118),
  catalog-only like the per-assignment queue below.
* ``/assignments`` — player preview, explicit consent, current assignment, and end.

The player and coach identities always come from the verified JWT. No request body
selects an account, and no raw invite code is ever logged.
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from service import analytics
from service import assignments as assignment_service
from service import analytics as analytics_service
from service import check_ins as check_ins_service
from service import checkpoint_reviews as checkpoint_reviews_service
from service import coach_history as coach_history_service
from service import coach_programs as coach_programs_service
from service import coach_program_drafts as coach_program_drafts_service
from service import program_requests as program_requests_service
from service.program_analytics import ProgramAnalyticsActor
from svc.dependencies import (
    VerifiedPlayer,
    get_current_coach,
    get_current_player,
    get_db,
    get_ledger,
    get_verified_player,
)
from svc.llm import register_ai_analytics_background_tasks
from svc.rate_limit import (
    ASSIGNMENT_INVITE_LIMIT,
    ASSIGNMENT_MUTATE_LIMIT,
    ASSIGNMENT_PREVIEW_LIMIT,
    ASSIGNMENT_REDEEM_LIMIT,
    limiter,
)
from svc.schemas import (
    AssignmentAccessOut,
    AssignmentEndOut,
    AssignmentInviteIssueOut,
    AssignmentInvitePreviewOut,
    AssignmentInviteTokenIn,
    AssignmentNoticeOut,
    AssignmentOut,
    AssignmentRedeemIn,
    AssignmentRedeemOut,
    CheckInIn,
    CheckInOut,
    CoachActiveProgramOut,
    CoachAssignmentsOut,
    CoachCheckInCreateOut,
    CheckpointReviewListItemOut,
    CheckpointReviewOut,
    CoachProgramApproveIn,
    CoachProgramDraftIn,
    CoachProgramDraftOut,
    CoachProgramPublishIn,
    CoachProgramPublicationOut,
    CoachCheckInListOut,
    CoachCrossRosterProgramRequestListOut,
    CoachCrossRosterProgramRequestOut,
    CoachExerciseHistoryOut,
    CoachIdentityOut,
    CoachNoticeListOut,
    CoachPersonalRecordOut,
    CoachPlayerExerciseOut,
    CoachPlayerExercisesOut,
    CoachPlayerSummaryOut,
    CoachProgramRequestListOut,
    CoachRosterEntryOut,
    PlayerCheckInListOut,
    PlayerNoticeListOut,
    PlayerProgramRequestIn,
    PlayerProgramRequestListOut,
    ProgramGenerateIn,
    ProgramRequestDeclineIn,
    ProgramRequestOut,
)

coach_router = APIRouter(prefix="/coach/assignments", tags=["coach"])
coach_roster_router = APIRouter(prefix="/coach", tags=["coach"])
player_router = APIRouter(prefix="/assignments", tags=["assignments"])


def _bad_request(error: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)


def _no_active_assignment() -> HTTPException:
    """One generic 403 for unknown, revoked, and other-coach assignments alike."""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=coach_history_service.DENIED_ERROR)


def _assignment_out(assignment: dict[str, Any]) -> AssignmentOut:
    return AssignmentOut(
        assignment_id=assignment["assignment_id"],
        coach=CoachIdentityOut(**assignment["coach"]),
        started_at=assignment["started_at"],
        status=assignment["status"],
        coach_preparing_program=assignment["coach_preparing_program"],
    )


async def _run_program_draft_action(action, *args, **kwargs):
    try:
        return await asyncio.to_thread(action, *args, **kwargs)
    except coach_program_drafts_service.ProgramDraftNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Coach side
# --------------------------------------------------------------------------


@coach_router.get("/{assignment_id}/program", response_model=CoachActiveProgramOut)
async def read_assigned_player_active_program(
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    program = await asyncio.to_thread(
        coach_history_service.active_program, db, coach.account_id, assignment_id
    )
    if program is None:
        raise _no_active_assignment()
    return CoachActiveProgramOut(**program)


@coach_router.post("/invites", response_model=AssignmentInviteIssueOut)
@limiter.limit(ASSIGNMENT_INVITE_LIMIT)
async def issue_assignment_invite(
    request: Request,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Issues a single-use, capacity-bound assignment invite for the authenticated coach."""
    client = analytics_service.client_context(request)

    def _run():
        result = assignment_service.issue_assignment_invite(db, coach.account_id, client=client)
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AssignmentInviteIssueOut(**result)


@coach_router.get("", response_model=CoachAssignmentsOut)
async def list_coach_assignments(
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists the coach's active assignments in roster urgency order (ticket #118).

    Each row carries its urgency inputs (badges, pending requests, last workout),
    so the client neither sorts nor fetches anything per player.
    """

    rows = await asyncio.to_thread(assignment_service.list_coach_assignments, db, coach.account_id)
    return CoachAssignmentsOut(assignments=[CoachRosterEntryOut(**row) for row in rows])


@coach_router.get("/{assignment_id}/player/summary", response_model=CoachPlayerSummaryOut)
async def read_assigned_player_summary(
    request: Request,
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    days: int = 7,
):
    """Volume and recent sessions for an actively assigned player."""

    def _run():
        summary = coach_history_service.player_summary(
            db,
            coach.account_id,
            assignment_id,
            days_lookback=max(1, min(days, 90)),
            client=analytics_service.client_context(request),
        )
        if summary is None:
            raise _no_active_assignment()
        return summary

    return CoachPlayerSummaryOut(**await asyncio.to_thread(_run))


@coach_router.get("/{assignment_id}/player/personal-records", response_model=list[CoachPersonalRecordOut])
async def read_assigned_player_personal_records(
    request: Request,
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    limit: int = 20,
):
    """The assigned player's recent personal records, newest-first."""

    def _run():
        records = coach_history_service.player_personal_records(
            db,
            coach.account_id,
            assignment_id,
            limit=max(1, min(limit, 100)),
            client=analytics_service.client_context(request),
        )
        if records is None:
            raise _no_active_assignment()
        return records

    return [CoachPersonalRecordOut(**record) for record in await asyncio.to_thread(_run)]


@coach_router.get(
    "/{assignment_id}/player/checkpoint-reviews",
    response_model=list[CheckpointReviewListItemOut],
)
async def list_assigned_player_checkpoint_reviews(
    request: Request,
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    reviews = await asyncio.to_thread(
        checkpoint_reviews_service.coach_checkpoint_reviews,
        db,
        coach.account_id,
        assignment_id,
        client=analytics_service.client_context(request),
    )
    if reviews is None:
        raise _no_active_assignment()
    return reviews


@coach_router.get(
    "/{assignment_id}/player/checkpoint-reviews/{checkpoint}",
    response_model=CheckpointReviewOut,
)
async def read_assigned_player_checkpoint_review(
    request: Request,
    assignment_id: str,
    checkpoint: int,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    try:
        review = await asyncio.to_thread(
            checkpoint_reviews_service.coach_checkpoint_review,
            db,
            coach.account_id,
            assignment_id,
            checkpoint,
            client=analytics_service.client_context(request),
        )
    except checkpoint_reviews_service.CheckpointReviewNotFoundError:
        raise HTTPException(status_code=404, detail="Checkpoint review not found.")
    if review is None:
        raise _no_active_assignment()
    return review


@coach_router.get("/{assignment_id}/player/exercises", response_model=CoachPlayerExercisesOut)
async def read_assigned_player_exercises(
    request: Request,
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """The distinct exercises the assigned player has logged."""

    def _run():
        exercises = coach_history_service.player_exercises(
            db,
            coach.account_id,
            assignment_id,
            client=analytics_service.client_context(request),
        )
        if exercises is None:
            raise _no_active_assignment()
        return exercises

    rows = await asyncio.to_thread(_run)
    return CoachPlayerExercisesOut(exercises=[CoachPlayerExerciseOut(**row) for row in rows])


@coach_router.get("/{assignment_id}/player/exercises/{exercise_id}/history", response_model=CoachExerciseHistoryOut)
async def read_assigned_player_exercise_history(
    request: Request,
    assignment_id: str,
    exercise_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Progression history, latest caption, and records for one exercise."""

    def _run():
        history = coach_history_service.player_exercise_history(
            db,
            coach.account_id,
            assignment_id,
            exercise_id,
            client=analytics_service.client_context(request),
        )
        if history is None:
            raise _no_active_assignment()
        return history

    return CoachExerciseHistoryOut(**await asyncio.to_thread(_run))


@coach_router.post("/{assignment_id}/check-ins", response_model=CoachCheckInCreateOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def create_assignment_check_in(
    request: Request,
    assignment_id: str,
    body: CheckInIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Records an immutable check-in for an actively assigned player (ADR 031)."""

    def _run():
        result = check_ins_service.create_check_in(
            db,
            coach.account_id,
            assignment_id,
            body.model_dump(),
            client=analytics_service.client_context(request),
        )
        if not result["ok"]:
            if result.get("denied"):
                raise _no_active_assignment()
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return CoachCheckInCreateOut(
        check_in=CheckInOut(**result["check_in"]),
        next_follow_up_on=result["next_follow_up_on"],
    )


@coach_router.get("/{assignment_id}/check-ins", response_model=CoachCheckInListOut)
async def list_assignment_check_ins(
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists an actively assigned player's check-ins, newest date first (catalog-only)."""

    rows = await asyncio.to_thread(check_ins_service.list_coach_check_ins, db, coach.account_id, assignment_id)
    if rows is None:
        raise _no_active_assignment()
    return CoachCheckInListOut(check_ins=[CheckInOut(**row) for row in rows])


@coach_router.get("/notices", response_model=CoachNoticeListOut)
async def list_coach_notices(
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists the coach's assignment notices newest-first."""

    rows = await asyncio.to_thread(assignment_service.list_coach_notices, db, coach.account_id)
    return CoachNoticeListOut(notices=[AssignmentNoticeOut(**row) for row in rows])


@coach_router.post("/notices/read")
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def mark_coach_notices_read(
    request: Request,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Marks all of the coach's notices read."""

    count = await asyncio.to_thread(assignment_service.mark_coach_notices_read, db, coach.account_id)
    return {"marked_read": count}


@coach_router.post("/{assignment_id}/revoke", response_model=AssignmentEndOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def revoke_assignment(
    request: Request,
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Coach ends one of their assignments; access is revoked immediately."""
    client = analytics_service.client_context(request)

    def _run():
        result = assignment_service.end_assignment(
            db, coach.account_id, assignment_id, "coach", client=client
        )
        if not result["ok"]:
            if "not part of this assignment" in result["error"]:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result["error"])
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AssignmentEndOut(**result)


@coach_router.post("/{assignment_id}/program-draft", response_model=CoachProgramDraftOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def create_assigned_player_program_draft(
    request: Request,
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    body: CoachProgramDraftIn | None = None,
):
    def _run():
        initial_draft = (body or CoachProgramDraftIn()).model_dump()
        try:
            created = coach_program_drafts_service.create_program_draft(
                db, coach.account_id, assignment_id, initial_draft
            )
        except coach_program_drafts_service.ProgramDraftAlreadyExists as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if created is None:
            raise _no_active_assignment()
        return created

    return await asyncio.to_thread(_run)


@coach_router.post(
    "/{assignment_id}/program-draft/copy-active",
    response_model=CoachProgramDraftOut,
)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def copy_assigned_player_active_program_to_draft(
    request: Request,
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    replace: bool = False,
):
    def _run():
        try:
            copied = coach_program_drafts_service.copy_active_program_to_draft(
                db, coach.account_id, assignment_id, replace=replace
            )
        except coach_program_drafts_service.ProgramDraftAlreadyExists as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except coach_program_drafts_service.ActiveProgramNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except coach_program_drafts_service.ProgramDraftValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"errors": exc.issues},
            ) from exc
        if copied is None:
            raise _no_active_assignment()
        return copied

    return await asyncio.to_thread(_run)


@coach_router.post("/{assignment_id}/program/approve", response_model=CoachProgramPublicationOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def approve_assigned_player_active_program(
    request: Request,
    assignment_id: str,
    body: CoachProgramApproveIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        try:
            published = coach_program_drafts_service.approve_active_program(
                db,
                coach.account_id,
                assignment_id,
                body.expected_active_version,
                client=analytics.client_context(request),
                resolve_request_ids=body.resolve_request_ids,
            )
        except coach_program_drafts_service.ActiveProgramNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except coach_program_drafts_service.ActiveProgramVersionMismatch as exc:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"error": "program_version_mismatch", "active_version": exc.active_version},
            )
        except coach_program_drafts_service.ProgramDraftValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"errors": exc.issues},
            ) from exc
        except program_requests_service.ProgramRequestSelectionError as exc:
            raise _bad_request(str(exc)) from exc
        if published is None:
            raise _no_active_assignment()
        return CoachProgramPublicationOut(
            **published.program.model_dump(),
            resolved_request_ids=published.resolved_request_ids,
        )

    return await asyncio.to_thread(_run)


@coach_router.post("/{assignment_id}/program-draft/generate", response_model=CoachProgramDraftOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def generate_assigned_player_program_draft(
    request: Request,
    background_tasks: BackgroundTasks,
    assignment_id: str,
    body: ProgramGenerateIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    replace: bool = False,
):
    register_ai_analytics_background_tasks(request, background_tasks)
    client = analytics.client_context(request)

    def _run():
        try:
            generated = coach_programs_service.generate_program_draft(
                db,
                ProgramAnalyticsActor(coach.account_id, "coach"),
                assignment_id,
                coach_programs_service.ProgramGenerationRequest(
                    user_split_override=body.user_split_override,
                    rep_preference_override=body.rep_preference_override,
                    frequency_override=body.frequency_override,
                ),
                replace_existing=replace,
                client=client,
                background_tasks=background_tasks,
            )
        except coach_program_drafts_service.ProgramDraftAlreadyExists as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except coach_program_drafts_service.ProgramDraftValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"errors": exc.issues},
            ) from exc
        if generated is None:
            raise _no_active_assignment()
        return generated

    return await asyncio.to_thread(_run)


@coach_router.get("/{assignment_id}/program-draft", response_model=CoachProgramDraftOut)
async def read_assigned_player_program_draft(
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    draft = await _run_program_draft_action(
        coach_program_drafts_service.read_program_draft, db, coach.account_id, assignment_id
    )
    if draft is None:
        raise _no_active_assignment()
    return draft


@coach_router.put("/{assignment_id}/program-draft", response_model=CoachProgramDraftOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def replace_assigned_player_program_draft(
    request: Request,
    assignment_id: str,
    body: CoachProgramDraftIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    replaced = await _run_program_draft_action(
        coach_program_drafts_service.replace_program_draft,
        db,
        coach.account_id,
        assignment_id,
        body.model_dump(),
    )
    if replaced is None:
        raise _no_active_assignment()
    return replaced


@coach_router.delete("/{assignment_id}/program-draft", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def discard_assigned_player_program_draft(
    request: Request,
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    discarded = await asyncio.to_thread(
        coach_program_drafts_service.discard_program_draft, db, coach.account_id, assignment_id
    )
    if discarded is None:
        raise _no_active_assignment()
    if not discarded:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program draft not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@coach_router.post("/{assignment_id}/program-draft/publish", response_model=CoachProgramPublicationOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def publish_assigned_player_program_draft(
    request: Request,
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    body: CoachProgramPublishIn | None = None,
):
    try:
        published = await _run_program_draft_action(
            coach_program_drafts_service.publish_program_draft,
            db,
            coach.account_id,
            assignment_id,
            analytics.client_context(request),
            resolve_request_ids=body.resolve_request_ids if body is not None else [],
        )
    except coach_program_drafts_service.ProgramDraftValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"errors": exc.issues},
        ) from exc
    except program_requests_service.ProgramRequestSelectionError as exc:
        raise _bad_request(str(exc)) from exc
    if published is None:
        raise _no_active_assignment()
    return CoachProgramPublicationOut(
        **published.program.model_dump(),
        resolved_request_ids=published.resolved_request_ids,
    )


@coach_roster_router.get("/program-requests", response_model=CoachCrossRosterProgramRequestListOut)
async def list_coach_program_requests(
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists the coach's program requests across every active assignment (ticket #118).

    Pending requests come first (oldest first), then answered ones (most recent
    first); requests from ended assignments are not listed. Each row carries the
    per-assignment fields plus ``assignment_id`` and the player's username, so the
    client can apply or decline through the existing per-assignment endpoints.
    """

    rows = await asyncio.to_thread(program_requests_service.list_coach_program_requests, db, coach.account_id)
    return CoachCrossRosterProgramRequestListOut(requests=[CoachCrossRosterProgramRequestOut(**row) for row in rows])


@coach_router.get("/{assignment_id}/program-requests", response_model=CoachProgramRequestListOut)
async def list_assignment_program_requests(
    assignment_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists an actively assigned player's program requests (catalog-only, newest-first)."""

    def _run():
        requests = program_requests_service.list_assignment_requests(db, coach.account_id, assignment_id)
        if requests is None:
            raise _no_active_assignment()
        return requests

    rows = await asyncio.to_thread(_run)
    return CoachProgramRequestListOut(requests=[ProgramRequestOut(**row) for row in rows])


@coach_router.post("/{assignment_id}/program-requests/{request_id}/apply", response_model=ProgramRequestOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def apply_assignment_program_request(
    request: Request,
    background_tasks: BackgroundTasks,
    assignment_id: str,
    request_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Revalidates and applies a pending request, publishing a new immutable version."""

    register_ai_analytics_background_tasks(request, background_tasks)

    def _run():
        result = program_requests_service.apply_request(
            db,
            ProgramAnalyticsActor(coach.account_id, "coach"),
            assignment_id,
            request_id,
            client=analytics.client_context(request),
            background_tasks=background_tasks,
        )
        if result is None:
            raise _no_active_assignment()
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result["request"]

    return ProgramRequestOut(**await asyncio.to_thread(_run))


@coach_router.post("/{assignment_id}/program-requests/{request_id}/decline", response_model=ProgramRequestOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def decline_assignment_program_request(
    request: Request,
    assignment_id: str,
    request_id: str,
    body: ProgramRequestDeclineIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Declines a pending request with a short player-visible response."""

    def _run():
        result = program_requests_service.decline_request(
            db,
            ProgramAnalyticsActor(coach.account_id, "coach"),
            assignment_id,
            request_id,
            body.response,
            client=analytics.client_context(request),
        )
        if result is None:
            raise _no_active_assignment()
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result["request"]

    return ProgramRequestOut(**await asyncio.to_thread(_run))


# --------------------------------------------------------------------------
# Player side
# --------------------------------------------------------------------------


@player_router.post("/invites/preview", response_model=AssignmentInvitePreviewOut)
@limiter.limit(ASSIGNMENT_PREVIEW_LIMIT)
async def preview_assignment_invite(
    request: Request,
    body: AssignmentInviteTokenIn,
    player: Annotated[VerifiedPlayer, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Shows the coach identity and exact access without consuming the code.

    The code travels in the body, never the URL, so it cannot leak through access logs.
    """

    def _run():
        result = assignment_service.preview_assignment_invite(db, body.token, player.account_id)
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AssignmentInvitePreviewOut(
        coach=CoachIdentityOut(**result["coach"]),
        access=AssignmentAccessOut(**result["access"]),
        expires_at=result["expires_at"],
    )


@player_router.post("/invites/redeem", response_model=AssignmentRedeemOut)
@limiter.limit(ASSIGNMENT_REDEEM_LIMIT)
async def redeem_assignment_invite(
    request: Request,
    body: AssignmentRedeemIn,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
    ledger: Annotated[Any, Depends(get_ledger)],
):
    """Explicitly consents to and atomically redeems an assignment invite."""
    client = analytics_service.client_context(request)

    def _run():
        redemption = assignment_service.redeem_assignment_invite(
            db,
            body.token,
            player.account_id,
            body.consent,
            ledger=ledger,
            client=client,
        )
        if not redemption["ok"]:
            raise _bad_request(redemption["error"])
        return redemption

    result = await asyncio.to_thread(_run)
    return AssignmentRedeemOut(
        assignment=_assignment_out(result["assignment"]),
        notices_created=result["notices_created"],
        email_sent=result["email_sent"],
    )


@player_router.get("/me", response_model=AssignmentOut | None)
async def read_my_assignment(
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
    ledger: Annotated[Any, Depends(get_ledger)],
):
    """The caller's active assignment, or ``null`` when none is active."""

    assignment = await asyncio.to_thread(
        assignment_service.get_player_assignment, db, player.account_id, ledger
    )
    return _assignment_out(assignment) if assignment is not None else None


@player_router.get("/me/check-ins", response_model=PlayerCheckInListOut)
async def list_my_check_ins(
    player: Annotated[VerifiedPlayer, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists the caller's check-ins across all assignments, including ended ones.

    The rows survive unassignment, so the player keeps their check-in history even
    after the former coach's access ends (ADR 031).
    """

    rows = await asyncio.to_thread(check_ins_service.list_player_check_ins, db, player.account_id)
    return PlayerCheckInListOut(check_ins=[CheckInOut(**row) for row in rows])


@player_router.get("/notices", response_model=PlayerNoticeListOut)
async def list_player_notices(
    player: Annotated[VerifiedPlayer, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists the player's assignment notices newest-first."""

    rows = await asyncio.to_thread(assignment_service.list_player_notices, db, player.account_id)
    return PlayerNoticeListOut(notices=[AssignmentNoticeOut(**row) for row in rows])


@player_router.post("/notices/read")
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def mark_player_notices_read(
    request: Request,
    player: Annotated[VerifiedPlayer, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Marks all of the player's notices read."""

    count = await asyncio.to_thread(assignment_service.mark_player_notices_read, db, player.account_id)
    return {"marked_read": count}


@player_router.post("/notices/{notice_id}/dismiss-summary")
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def dismiss_player_program_change_summary(
    request: Request,
    notice_id: str,
    player: Annotated[VerifiedPlayer, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Dismiss one of the caller's program change summaries without changing read state."""
    dismissed = await asyncio.to_thread(
        assignment_service.dismiss_player_program_change_summary,
        db,
        player.account_id,
        notice_id,
    )
    if not dismissed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notice not found.")
    return {"dismissed": True}


@player_router.post("/me/end", response_model=AssignmentEndOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def end_my_assignment(
    request: Request,
    player: Annotated[VerifiedPlayer, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Player ends their active assignment; coach access is revoked immediately."""
    client = analytics_service.client_context(request)

    def _run():
        assignment_id = assignment_service.get_active_player_assignment_id(db, player.account_id)
        if assignment_id is None:
            raise _bad_request("You have no active coaching assignment.")
        result = assignment_service.end_assignment(
            db, player.account_id, assignment_id, "player", client=client
        )
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AssignmentEndOut(**result)


@player_router.get("/me/program-requests", response_model=PlayerProgramRequestListOut)
async def list_my_program_requests(
    player: Annotated[VerifiedPlayer, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists the caller's program requests, newest-first."""

    rows = await asyncio.to_thread(program_requests_service.list_player_requests, db, player.account_id)
    return PlayerProgramRequestListOut(requests=[ProgramRequestOut(**row) for row in rows])


@player_router.post("/me/program-requests", response_model=ProgramRequestOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def create_my_program_request(
    request: Request,
    body: PlayerProgramRequestIn,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Records a pending exercise-substitution or split-change request; the program is untouched."""

    def _run():
        return program_requests_service.create_request(
            db,
            ProgramAnalyticsActor(player.account_id, "player"),
            body.model_dump(),
            ledger=ledger,
            client=analytics.client_context(request),
        )

    result = await asyncio.to_thread(_run)
    if not result["ok"]:
        if "code" in result:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": result["error"], "code": result["code"]},
            )
        raise _bad_request(result["error"])
    return ProgramRequestOut(**result["request"])


@player_router.post("/me/program-requests/{request_id}/cancel", response_model=ProgramRequestOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def cancel_my_program_request(
    request: Request,
    request_id: str,
    player: Annotated[VerifiedPlayer, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Cancels the caller's own pending request."""

    def _run():
        result = program_requests_service.cancel_request(
            db,
            ProgramAnalyticsActor(player.account_id, "player"),
            request_id,
            client=analytics.client_context(request),
        )
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result["request"]

    return ProgramRequestOut(**await asyncio.to_thread(_run))
