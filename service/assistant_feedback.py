"""Assistant reply feedback contracts, signing, summaries, and Discord delivery."""

from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import logging
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

FEEDBACK_WEBHOOK_ENV = "DISCORD_FEEDBACK_WEBHOOK_URL"
NOTE_MAX_CHARS = 500
REASONS = {
    "wrong_information": "Wrong information",
    "not_helpful": "Not helpful",
    "didnt_understand": "Didn't understand me",
    "unsafe_advice": "Unsafe advice",
    "offensive": "Offensive",
}
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
# Identifier-like tokens only: 12+ chars that contain at least one digit, so
# ordinary long words ("Unfortunately", "recommendations") pass through.
_LONG_ID = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{12,}\b", re.IGNORECASE)


def _context_payload(
    *,
    message_id: str,
    question_text: str,
    reply_text: str,
    language: str,
    route: str,
    model: str | None,
    prompt_version: str | None,
    redact_terms: list[str] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "message_id": message_id,
        "question_text": question_text[:10000],
        "reply_text": reply_text[:20000],
        "language": language if language in {"en", "ar"} else "en",
        "route": (route or "assistant").strip()[:120],
        "model": model[:120] if model else None,
        "prompt_version": prompt_version[:160] if prompt_version else None,
        "redact_terms": [term.strip()[:120] for term in (redact_terms or []) if term.strip()][:30],
    }
    return context


def build_feedback_context(account_id: str, **kwargs: Any) -> dict[str, Any]:
    """Builds an account-bound context token for a completed assistant reply."""
    context = _context_payload(**kwargs)
    context["signature"] = _signature(account_id, context)
    return context


@lru_cache(maxsize=1)
def player_prompt_version() -> str:
    """Hashes the player prompt and graph source to pin the answering logic."""
    try:
        from agent import assistant_graph, player_prompt

        source = inspect.getsource(player_prompt) + inspect.getsource(assistant_graph)
    except (OSError, TypeError):
        return "player-chat-v1"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def configured_reply_model(model_type: str) -> str | None:
    """Current hosted model id for a route, so feedback carries what answered."""
    try:
        from utils.model_downloader import _cloud_model_id

        return _cloud_model_id(model_type)
    except Exception:
        return None


def validate_feedback_context(account_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Rejects forged or oversized client feedback contexts before any ledger write."""
    context = _context_payload(
        message_id=str(raw.get("message_id", "")),
        question_text=str(raw.get("question_text", "")),
        reply_text=str(raw.get("reply_text", "")),
        language=str(raw.get("language", "")),
        route=str(raw.get("route", "")),
        model=raw.get("model") if isinstance(raw.get("model"), str) else None,
        prompt_version=raw.get("prompt_version") if isinstance(raw.get("prompt_version"), str) else None,
        redact_terms=raw.get("redact_terms") if isinstance(raw.get("redact_terms"), list) else [],
    )
    signature = raw.get("signature")
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, _signature(account_id, context)
    ):
        raise ValueError("The feedback does not match a completed assistant reply.")
    if (
        not context["message_id"]
        or len(context["message_id"]) > 80
        or not context["question_text"]
        or not context["reply_text"]
        or not context["route"]
        or len(context["redact_terms"]) > 30
    ):
        raise ValueError("The feedback context is incomplete.")
    return context


def _signature(account_id: str, context: dict[str, Any]) -> str:
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET is required to sign assistant feedback context.")
    payload = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        secret.encode("utf-8"),
        f"assistant-feedback-v1\0{account_id}\0{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _redact_excerpt(text: str, terms: list[str]) -> str:
    # Account and Player names go first so the generic id/phone patterns can
    # never swallow them into an opaque "[redacted id]" (issue #748). Each
    # term matches as a whole word — a short preferred name ("Mo") must not
    # chew "more" into "[redacted]re" — and Python's \w is Unicode-aware, so
    # the same lookarounds work for Arabic names. Attached Arabic prefixes
    # (و، ف، ب، ل، ك، ال، وال، …, including stacked ones like فب) are captured
    # and kept so "وعمر" redacts the name while keeping the particle:
    # "و[redacted]".
    for term in sorted(set(terms), key=len, reverse=True):
        if len(term) < 2:
            continue
        text = re.sub(
            r"(?<!\w)((?:وال|فال|بال|كال|لل|ال|[وفبلك])*)" + re.escape(term) + r"(?!\w)",
            r"\1[redacted]",
            text,
            flags=re.IGNORECASE,
        )
    excerpt = _EMAIL.sub("[redacted email]", text)
    excerpt = _PHONE.sub("[redacted phone]", excerpt)
    excerpt = _UUID.sub("[redacted id]", excerpt)
    excerpt = _LONG_ID.sub("[redacted id]", excerpt)
    excerpt = " ".join(excerpt.split())
    if len(excerpt) > 220:
        excerpt = excerpt[:217].rsplit(" ", 1)[0] + "…"
    return excerpt or "[reply excerpt redacted]"


def _discord_post(content: str) -> bool:
    """Sends one message to the feedback webhook; True only on a 2xx.

    The single delivery seam for both reply reports and the weekly summary.
    Returns ``False`` when no webhook is configured or delivery fails. Tests
    patch this function; the webhook URL never enters logs or test payloads.
    """
    webhook = os.getenv(FEEDBACK_WEBHOOK_ENV, "").strip()
    if not webhook:
        return False
    try:
        from svc.monitoring.tiles.sentry_discord import _post, _webhook_url

        _webhook_url(webhook)
        status_code, _retry_after = _post(webhook, content)
    except Exception:
        # The webhook URL contains a credential; don't echo it or response bodies.
        logger.warning("Assistant feedback Discord delivery failed.")
        return False
    return 200 <= status_code < 300


def send_report_to_discord(
    context: dict[str, Any], feedback_id: str, reasons: list[str]
) -> bool:
    """Sends only owner-review fields; never includes an account or Player identity."""
    reason_text = ", ".join(REASONS.get(reason, "Other") for reason in reasons)
    content = "\n".join(
        (
            "MAYOS AI reply report",
            f"Feedback ID: {feedback_id}",
            f"Reason: {reason_text}",
            f"Language: {context['language']}",
            f"Route: {context['route']}",
            f"Reply: {_redact_excerpt(context['reply_text'], context['redact_terms'])}",
        )
    )
    return _discord_post(content)


def report_context_redact_terms(db: Any, account_id: str, own_ledger: Any) -> list[str]:
    """Collects account and active-coach names for Discord excerpt redaction only."""
    terms: list[str] = []
    account = db.get_account(account_id)
    if account:
        terms.append(str(account.get("username", "")))
    memory = own_ledger.get_assistant_memory()
    if memory and memory.get("preferred_name"):
        terms.append(str(memory["preferred_name"]))
    # Coach replies may refer to their assigned Player. Resolve names only for
    # redaction and never put them into the Discord payload.
    for assignment in db.list_active_assignments_for_coach(account_id):
        player = db.get_account(assignment["player_account_id"])
        if not player:
            continue
        terms.append(str(player.get("username", "")))
        try:
            with db.open_ledger(player["ledger_id"]) as player_ledger:
                player_memory = player_ledger.get_assistant_memory()
            if player_memory and player_memory.get("preferred_name"):
                terms.append(str(player_memory["preferred_name"]))
        except Exception:
            logger.info("Could not load a Player name for feedback excerpt redaction.")
    return [term.strip() for term in terms if term and term.strip()]


def coach_feedback_redact_terms(db: Any, coach_account_id: str) -> list[str]:
    """Coach-side redaction terms: coach names plus every assigned Player's names."""
    account = db.get_account(coach_account_id)
    if not account:
        return []
    try:
        with db.open_ledger(account["ledger_id"]) as ledger:
            return report_context_redact_terms(db, coach_account_id, ledger)
    except Exception:
        return []


def assistant_reply_metadata(
    *, language: str, route: str, model: str | None, prompt_version: str | None
) -> dict[str, Any]:
    """Builds the chat_history metadata columns that feedback re-derivation needs."""

    return {
        "language": (language or "en")[:8],
        "route": (route or "assistant").strip()[:120],
        "model": model[:120] if model else None,
        "prompt_version": prompt_version[:160] if prompt_version else None,
    }


def resolve_player_feedback_context(
    account_id: str,
    *,
    message_id: str,
    question_text: str,
    reply_text: str,
    language: str,
    route: str,
    redact_terms: list[str],
) -> dict[str, Any] | None:
    """Signs the feedback context for a just-finished player chat turn.

    Returns ``None`` when signing is unavailable so a chat turn never fails
    because feedback metadata could not be built.
    """
    try:
        return build_feedback_context(
            account_id,
            message_id=message_id,
            question_text=question_text,
            reply_text=reply_text,
            language=language,
            route=route,
            model=configured_reply_model("production"),
            prompt_version=player_prompt_version(),
            redact_terms=redact_terms,
        )
    except Exception:
        logger.info("Feedback context for a chat reply could not be signed.")
        return None


def resolve_coach_feedback_context(
    coach_account_id: str,
    *,
    message_id: str,
    question_text: str,
    reply_text: str,
    language: str,
    route: str,
    redact_terms: list[str],
) -> dict[str, Any] | None:
    """Signs the feedback context for a just-finished coach assistant turn."""
    try:
        return build_feedback_context(
            coach_account_id,
            message_id=message_id,
            question_text=question_text,
            reply_text=reply_text,
            language=language,
            route=route,
            model=configured_reply_model("coach"),
            prompt_version=player_prompt_version(),
            redact_terms=redact_terms,
        )
    except Exception:
        logger.info("Feedback context for a coach reply could not be signed.")
        return None


def feedback_context_from_ledger(
    account_id: str, ledger: Any, message_id: str, redact_terms: list[str] | None = None
) -> dict[str, Any] | None:
    """Re-derives a signed context from the ledger for a stored assistant reply.

    Covers votes and reports that arrive after the client's cached context is
    gone (process restarts, chat-history wipes of the client cache).
    """
    source = ledger.get_chat_message_feedback_source(message_id)
    if source is None:
        return None
    try:
        return build_feedback_context(
            account_id,
            message_id=source["message_id"],
            question_text=source["question_text"],
            reply_text=source["reply_text"],
            language=str(source["language"] or "en"),
            route=str(source["route"] or "assistant"),
            model=source["model"],
            prompt_version=source["prompt_version"],
            redact_terms=redact_terms or [],
        )
    except Exception:
        logger.info("Feedback context could not be re-derived from the ledger.")
        return None


def resolve_feedback_context(
    account_id: str,
    ledger: Any,
    db: Any | None,
    *,
    client_context: dict[str, Any] | None,
    message_id: str | None,
    with_redact_terms: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validates the client's signed context, else re-derives it from the ledger.

    Returns ``(context, error)``. ``error`` is a user-facing message when the
    request cannot be served; the caller turns it into a 400.
    """
    if client_context is not None:
        try:
            return validate_feedback_context(account_id, client_context), None
        except ValueError as error:
            return None, str(error)
    if not message_id:
        return None, "The reply to give feedback on could not be found."
    terms = report_context_redact_terms(db, account_id, ledger) if with_redact_terms else []
    context = feedback_context_from_ledger(account_id, ledger, message_id, redact_terms=terms)
    if context is None:
        return None, "The reply to give feedback on could not be found."
    return context, None


def record_vote(
    ledger: Any, account_id: str, context: dict[str, Any], payload: Any
) -> dict[str, Any] | None:
    """Stores a 👍/👎 (or clears it); a replay of the same vote changes nothing."""
    vote = payload.vote
    reasons = list(payload.reasons) if vote == "down" else []
    note = (payload.note or "").strip()[:NOTE_MAX_CHARS] or None
    return ledger.set_assistant_reply_vote(
        context, str(account_id), vote, reasons, note if vote == "down" else None
    )


def record_report(
    ledger: Any, account_id: str, context: dict[str, Any], payload: Any
) -> dict[str, Any]:
    """Records one report per reply and sends it straight to Discord."""
    note = (payload.note or "").strip()[:NOTE_MAX_CHARS] or None
    result = ledger.record_assistant_reply_report(
        context, str(account_id), list(payload.reasons), note
    )
    if result.get("created") and not result.get("delivery_pending"):
        if send_report_to_discord(context, str(result["feedback_id"]), list(payload.reasons)):
            ledger.mark_assistant_feedback_report_delivered(str(result["feedback_id"]))
            result["delivery_pending"] = False
        else:
            result["delivery_pending"] = True
    return result


def feedback_maintenance(db: Any, limit: int = 20) -> None:
    """Hourly background pass: retry undelivered reports, then the weekly summary."""
    try:
        retry_pending_reports(db, limit)
    except Exception:
        logger.exception("Assistant feedback report retry pass failed.")
    try:
        send_weekly_summary(db)
    except Exception:
        logger.exception("Assistant feedback weekly summary pass failed.")


def summarize_votes(db: Any, now: datetime | None = None) -> dict[str, Any] | None:
    """Builds the prior complete UTC week summary without exporting any text or ids."""
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    # Monday 09:00 UTC gives a full prior Monday–Sunday reporting window.
    if instant.weekday() != 0 or instant.hour < 9:
        return None
    end = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)
    week_key = start.date().isoformat()
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    by_route: dict[str, Counter[str]] = defaultdict(Counter)
    by_language: dict[str, Counter[str]] = defaultdict(Counter)
    for account in db.list_accounts():
        if account.get("deleted_at") is not None or not db.ledger_exists(account["ledger_id"]):
            continue
        try:
            with db.open_ledger(account["ledger_id"]) as ledger:
                rows = ledger.assistant_feedback_week_summary(
                    account["account_id"], start.isoformat(), end.isoformat()
                )
            for row in rows:
                counts[row["vote"]] += 1
                by_route[row["route"]][row["vote"]] += 1
                by_language[row["language"]][row["vote"]] += 1
                if row["vote"] == "down":
                    reasons.update(reason for reason in row["reasons"] if reason in REASONS)
        except Exception:
            logger.exception("Assistant feedback summary could not read a ledger.")
    return {
        "week": week_key,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "up": counts["up"],
        "down": counts["down"],
        "reasons": reasons,
        "by_route": by_route,
        "by_language": by_language,
    }


def format_weekly_summary(summary: dict[str, Any]) -> str:
    total = summary["up"] + summary["down"]
    rate = (summary["down"] / total * 100.0) if total else 0.0
    lines = [
        "MAYOS assistant feedback (UTC week starting " + summary["week"] + ")",
        f"👍 {summary['up']}  👎 {summary['down']}  👎 rate {rate:.1f}%",
    ]
    if summary["reasons"]:
        lines.append(
            "Top 👎 reasons: "
            + ", ".join(
                f"{REASONS[reason]} ({count})"
                for reason, count in summary["reasons"].most_common(5)
            )
        )
    for label, groups in (("route", summary["by_route"]), ("language", summary["by_language"])):
        if not groups:
            continue
        rows = []
        for key in sorted(groups):
            up, down = groups[key]["up"], groups[key]["down"]
            total = up + down
            rows.append(f"{key}: {down}/{total} 👎 ({(down / total * 100.0) if total else 0:.1f}%)")
        lines.append(f"👎 rate by {label}: " + "; ".join(rows))
    return "\n".join(lines)


def send_weekly_summary(db: Any, now: datetime | None = None) -> bool:
    summary = summarize_votes(db, now)
    if summary is None or (summary["up"] + summary["down"] == 0):
        return False
    webhook = os.getenv(FEEDBACK_WEBHOOK_ENV, "").strip()
    if not webhook:
        return False
    db.ensure_account_schema()
    if db.catalog_conn.execute(
        "SELECT 1 FROM assistant_feedback_summary_weeks WHERE week_start = ?",
        (summary["week"],),
    ).fetchone():
        return False
    if not _discord_post(format_weekly_summary(summary)):
        logger.warning("Assistant feedback weekly summary delivery failed.")
        return False
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute(
            "INSERT OR IGNORE INTO assistant_feedback_summary_weeks (week_start, sent_at) "
            "VALUES (?, ?)",
            (summary["week"], datetime.now(UTC).isoformat()),
        )
    return True


def retry_pending_reports(db: Any, limit: int = 20) -> int:
    webhook = os.getenv(FEEDBACK_WEBHOOK_ENV, "").strip()
    if not webhook:
        return 0
    delivered = 0
    for account in db.list_accounts():
        if account.get("deleted_at") is not None or not db.ledger_exists(account["ledger_id"]):
            continue
        try:
            with db.open_ledger(account["ledger_id"]) as ledger:
                for row in ledger.pending_assistant_feedback_reports(limit - delivered):
                    context = {
                        "reply_text": row["reply_text"],
                        "language": row["language"],
                        "route": row["route"],
                        "redact_terms": row["redact_terms"],
                    }
                    if send_report_to_discord(context, row["feedback_id"], row["reasons"]):
                        ledger.mark_assistant_feedback_report_delivered(row["feedback_id"])
                        delivered += 1
                        if delivered >= limit:
                            break
                # Clearing chat history keeps undelivered reports; a delivered
                # report whose message is gone has no remaining surface.
                ledger.delete_delivered_feedback_without_message()
        except Exception:
            logger.exception("Assistant feedback report retry failed for a ledger.")
    return delivered


def new_feedback_message_id() -> str:
    return str(uuid.uuid4())

