"""Player program requests and coach resolution (ticket #28, ADR 018/027).

A player on a coach-controlled program requests an exercise substitution or a
split change. The request is stored catalog-side against the active assignment
and pins the exact program version, day, and slot it targets; creating a request
never touches the player's program. The coach resolves it through the
assignment-gated routes: apply revalidates against the active program and, on a
match, claims the pending row before writing a NEW immutable program version so
the requested version is never mutated in place; decline carries a short
player-visible response. The player may cancel their own pending request.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from agent.program_generator import generate_program_pipeline
from service._base import ledger_scope
from service.assignments import authorized_player_ledger, coach_identity
from service.email_sender import send_program_request_email
from service.programs import player_controls_program
from service.program_substitution import ProgramSubstitution, substitute_program_exercise

logger = logging.getLogger(__name__)

DIRECT_CHANGE_ERROR = "You can change your own program directly."
STALE_REQUEST_ERROR = "The program changed since this request was created. Ask the player to update it."
NOT_PENDING_ERROR = "This request is no longer pending."
REQUEST_NOT_FOUND_ERROR = "Request not found."

EXERCISE_SUBSTITUTION = "exercise_substitution"
SPLIT_CHANGE = "split_change"
REQUEST_KINDS = {EXERCISE_SUBSTITUTION, SPLIT_CHANGE}

MAX_REASON_CHARS = 500
MAX_RESPONSE_CHARS = 500
MAX_SPLIT_PREFERENCE_CHARS = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _find_day(program: Any, day_name: Any) -> Any:
    return next((day for day in program.days if day.day_name == day_name), None)


def _day_contains(program: Any, day_name: Any, exercise_id: Any) -> bool:
    day = _find_day(program, day_name)
    if day is None:
        return False
    return any(str(exercise.exercise_id) == str(exercise_id) for exercise in day.exercises)


def _notify_player(
    db: Any, player_account_id: str, assignment_id: str, message: str, now_iso: str
) -> None:
    """Best-effort player in-app notice; a notice failure never fails the resolution."""
    try:
        db.create_assignment_notice(player_account_id, assignment_id, "program_request", message, now_iso)
    except Exception:
        logger.exception("Player program-request notice raised unexpectedly")


def create_request(
    db: Any, player_account_id: str, payload: dict[str, Any], ledger: Any | None = None
) -> dict[str, Any]:
    """Records a pending request against the player's coach-controlled active program.

    Returns ``{"ok": False, "error": ...}`` for a refusal and never writes the
    program. The exact active version, day, and slot are pinned on the request.
    """
    kind = payload.get("kind")
    if kind not in REQUEST_KINDS:
        return {"ok": False, "error": "Choose an exercise substitution or a split change."}

    reason = str(payload.get("reason") or "").strip()
    if not reason:
        return {"ok": False, "error": "A reason is required."}
    if len(reason) > MAX_REASON_CHARS:
        return {"ok": False, "error": f"Keep the reason under {MAX_REASON_CHARS} characters."}

    account = db.get_account(player_account_id)
    if not db.is_live_account(account):
        return {"ok": False, "error": DIRECT_CHANGE_ERROR}

    with ledger_scope(db, ledger, account["ledger_id"]) as ledger:
        if player_controls_program(db, ledger, player_account_id):
            return {"ok": False, "error": DIRECT_CHANGE_ERROR}

        assignment = db.get_active_assignment_for_player(player_account_id)
        if assignment is None:
            return {"ok": False, "error": DIRECT_CHANGE_ERROR}

        active = ledger.get_active_program()
        if active is None:
            return {"ok": False, "error": "You do not have an active program to change."}

        day_name = exercise_id = replacement_exercise_id = None
        desired_weekly_frequency = None
        desired_split_preference = None

        if kind == EXERCISE_SUBSTITUTION:
            day_name = str(payload.get("day_name") or "").strip()
            exercise_id = payload.get("exercise_id")
            replacement_exercise_id = payload.get("replacement_exercise_id")
            if not day_name or not exercise_id or not replacement_exercise_id:
                return {"ok": False, "error": "Pick the day, the exercise, and its replacement."}
            if str(replacement_exercise_id) == str(exercise_id):
                return {"ok": False, "error": "Choose a different replacement exercise."}
            if _find_day(active, day_name) is None:
                return {"ok": False, "error": "That day is not part of your current program."}
            if not _day_contains(active, day_name, exercise_id):
                return {"ok": False, "error": "That exercise is not in that day of your current program."}
            if db.get_exercise_library_entry(str(replacement_exercise_id)) is None:
                return {"ok": False, "error": "That replacement exercise was not found."}
            exercise_id = str(exercise_id)
            replacement_exercise_id = str(replacement_exercise_id)
        else:
            desired_weekly_frequency = payload.get("desired_weekly_frequency")
            if (
                isinstance(desired_weekly_frequency, bool)
                or not isinstance(desired_weekly_frequency, int)
                or not 1 <= desired_weekly_frequency <= 5
            ):
                return {"ok": False, "error": "Weekly frequency must be between 1 and 5."}
            desired_split_preference = str(payload.get("desired_split_preference") or "").strip() or None
            if desired_split_preference and len(desired_split_preference) > MAX_SPLIT_PREFERENCE_CHARS:
                return {"ok": False, "error": f"Keep the split preference under {MAX_SPLIT_PREFERENCE_CHARS} characters."}

        now_iso = _now_iso()
        request_id = uuid.uuid4().hex
        coach_account_id = assignment["coach_account_id"]
        db.create_program_request(
            request_id=request_id,
            assignment_id=assignment["assignment_id"],
            coach_account_id=coach_account_id,
            player_account_id=str(player_account_id),
            kind=kind,
            program_version=int(active.version or 0),
            day_name=day_name,
            exercise_id=exercise_id,
            replacement_exercise_id=replacement_exercise_id,
            desired_weekly_frequency=desired_weekly_frequency,
            desired_split_preference=desired_split_preference,
            reason=reason,
            now_iso=now_iso,
        )
        email_sent = _notify_coach(
            db, coach_account_id, assignment["assignment_id"], account["username"], now_iso
        )

        request = db.get_program_request(request_id)
        return {"ok": True, "request": request, "email_sent": email_sent}


def _notify_coach(
    db: Any, coach_account_id: str, assignment_id: str, player_username: str, now_iso: str
) -> bool:
    """Generic in-app + email coach notice; neither path ever carries training detail.

    The two paths are independent best-effort side effects: one failing never
    suppresses the other, and only the email outcome is reported back.
    """
    try:
        db.create_assignment_notice(
            coach_account_id,
            assignment_id,
            "program_request",
            f"{player_username} requested a program change. Review it in your roster.",
            now_iso,
        )
    except Exception:
        logger.exception("Coach program-request notice raised unexpectedly")
    email_sent = False
    try:
        coach_account = db.get_account(coach_account_id)
        if coach_account:
            to_email = db.get_account_email(coach_account["account_id"])
            if to_email:
                display_name = coach_identity(db, coach_account_id, coach_account)["display_name"]
                send_program_request_email(to_email, display_name, player_username)
                email_sent = True
    except Exception:
        logger.exception("Coach program-request email raised unexpectedly")
    return email_sent


def _pending_request(db: Any, coach_account_id: str, assignment_id: Any, request_id: Any) -> Any:
    request = db.get_program_request(request_id) if isinstance(request_id, str) and request_id else None
    if request is None or request["assignment_id"] != str(assignment_id):
        return None
    if request["coach_account_id"] != str(coach_account_id):
        return None
    return request


def apply_request(
    db: Any, coach_account_id: str, assignment_id: Any, request_id: Any
) -> dict[str, Any] | None:
    """Revalidates and applies a pending request, writing a NEW immutable program version.

    ``None`` is the generic assignment denial. A stale target stays pending and
    leaves the program untouched; the pending→applied claim runs before any write
    so a double apply or a racing cancel cannot both succeed.
    """
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        request = _pending_request(db, coach_account_id, assignment_id, request_id)
        if request is None:
            return {"ok": False, "error": REQUEST_NOT_FOUND_ERROR}
        if request["status"] != "pending":
            return {"ok": False, "error": NOT_PENDING_ERROR}

        active = ledger.get_active_program()
        stale = (
            active is None
            or int(active.version or 0) != int(request["program_version"])
            or player_controls_program(db, ledger, request["player_account_id"])
        )
        if not stale and request["kind"] == EXERCISE_SUBSTITUTION:
            stale = not _day_contains(active, request["day_name"], request["exercise_id"])
        if stale:
            return {"ok": False, "error": STALE_REQUEST_ERROR, "stale": True}

        if request["kind"] == EXERCISE_SUBSTITUTION:
            if db.get_exercise_library_entry(request["replacement_exercise_id"]) is None:
                return {"ok": False, "error": STALE_REQUEST_ERROR, "stale": True}

        claimed = db.resolve_program_request(request_id, "applied", None, coach_account_id, _now_iso())
        if not claimed["ok"]:
            return {"ok": False, "error": NOT_PENDING_ERROR}

        try:
            if request["kind"] == EXERCISE_SUBSTITUTION:
                substitution = substitute_program_exercise(
                    ledger,
                    db,
                    active,
                    ProgramSubstitution(
                        day_name=request["day_name"],
                        exercise_id=request["exercise_id"],
                        replacement_exercise_id=request["replacement_exercise_id"],
                        published_by_coach_account_id=coach_account_id,
                    ),
                )
                if not substitution["ok"]:
                    reverted = db.reopen_program_request(request_id, _now_iso())
                    if not reverted["ok"]:
                        logger.error(
                            "Program request %s could not be reverted after substitution validation",
                            request_id,
                        )
                    if substitution["error"] in {
                        "That day is not part of your current program.",
                        "That exercise is not in that day of your current program.",
                    }:
                        return {"ok": False, "error": STALE_REQUEST_ERROR, "stale": True}
                    return {"ok": False, "error": substitution["error"]}
            else:
                from svc.llm import InferenceScope, run_inference_sync

                run_inference_sync(
                    generate_program_pipeline,
                    frequency_override=request["desired_weekly_frequency"],
                    user_split_override=request["desired_split_preference"],
                    published_by_coach_account_id=coach_account_id,
                    ledger=ledger,
                    scope=InferenceScope(
                        account_id=coach_account_id, role="coach", purpose="coach_program_request", store=db
                    ),
                )
        except Exception:
            logger.exception(
                "Program request %s write failed after claim; reverting to pending", request_id
            )
            now_iso = _now_iso()
            try:
                reverted = db.reopen_program_request(request_id, now_iso)
                if not reverted["ok"]:
                    logger.error(
                        "Program request %s could not be reverted to pending (rowcount=%s)",
                        request_id,
                        reverted["rowcount"],
                    )
            except Exception:
                logger.exception("Program request %s revert raised unexpectedly", request_id)
            raise

        published = ledger.get_active_program()
        version = published.version if published is not None else None
        _notify_player(
            db,
            request["player_account_id"],
            request["assignment_id"],
            f"Your coach applied your program change. Program version {version}.",
            _now_iso(),
        )
        return {"ok": True, "request": db.get_program_request(request_id), "program_version": version}


def decline_request(
    db: Any, coach_account_id: str, assignment_id: Any, request_id: Any, response: str
) -> dict[str, Any] | None:
    """Declines a pending request with a short player-visible response; program untouched."""
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        response = str(response or "").strip()
        if not response:
            return {"ok": False, "error": "A response is required."}
        if len(response) > MAX_RESPONSE_CHARS:
            return {"ok": False, "error": f"Keep the response under {MAX_RESPONSE_CHARS} characters."}

        request = _pending_request(db, coach_account_id, assignment_id, request_id)
        if request is None:
            return {"ok": False, "error": REQUEST_NOT_FOUND_ERROR}
        if request["status"] != "pending":
            return {"ok": False, "error": NOT_PENDING_ERROR}

        claimed = db.resolve_program_request(request_id, "declined", response, coach_account_id, _now_iso())
        if not claimed["ok"]:
            return {"ok": False, "error": NOT_PENDING_ERROR}

        _notify_player(
            db,
            request["player_account_id"],
            request["assignment_id"],
            f"Your coach declined your program change: {response}",
            _now_iso(),
        )
        return {"ok": True, "request": db.get_program_request(request_id)}


def cancel_request(db: Any, player_account_id: str, request_id: Any) -> dict[str, Any]:
    """Cancels the player's own pending request; another player's or a resolved one is refused."""
    request = db.get_program_request(request_id) if isinstance(request_id, str) and request_id else None
    if request is None or request["player_account_id"] != str(player_account_id):
        return {"ok": False, "error": REQUEST_NOT_FOUND_ERROR}
    if request["status"] != "pending":
        return {"ok": False, "error": NOT_PENDING_ERROR}
    claimed = db.resolve_program_request(request_id, "cancelled", None, "player", _now_iso())
    if not claimed["ok"]:
        return {"ok": False, "error": NOT_PENDING_ERROR}
    return {"ok": True, "request": db.get_program_request(request_id)}


def list_player_requests(db: Any, player_account_id: str) -> list[dict[str, Any]]:
    return db.list_program_requests_for_player(player_account_id)


def list_assignment_requests(
    db: Any, coach_account_id: str, assignment_id: Any
) -> list[dict[str, Any]] | None:
    """Catalog-only queue listing; ``None`` is the generic denial (no ledger mounted)."""
    if not isinstance(assignment_id, str) or not assignment_id:
        return None
    if db.get_active_assignment_for_coach(coach_account_id, assignment_id) is None:
        return None
    return db.list_program_requests_for_assignment(assignment_id)


def list_coach_program_requests(db: Any, coach_account_id: str) -> list[dict[str, Any]]:
    """The coach's requests across every active assignment, pending first (#118).

    Pending rows come first, oldest first, then answered rows, most recently
    resolved first. Requests on ended assignments and from other coaches are
    excluded, and each row carries ``assignment_id`` and the player's username
    beside the per-assignment fields, so the client resolves through the existing
    per-assignment endpoints. Catalog-only; no ledger mount.
    """
    return db.list_program_requests_for_coach(coach_account_id)
