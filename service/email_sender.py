"""Outbound email for account recovery, owner login, and assignment notices.

Production delivery requires SMTP_* env (see .env.example). When SMTP_HOST is
unset, the message is logged server-side instead of sent — safe for local dev,
never for shared hosting. This module never raises for transport issues; callers
log the boolean and keep generic client responses.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from utils.env_flags import env_flag

logger = logging.getLogger(__name__)
# Keep missing-secret development runs from using a guessable, unkeyed digest.
_FALLBACK_EMAIL_HASH_KEY = secrets.token_bytes(32)
_EMAIL_ADDRESS_TOKEN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+(?![A-Za-z0-9.-])"
)

PURPOSE_PASSWORD_RESET = "password_reset"
PURPOSE_ASSIGNMENT_NOTICE = "assignment_notice"
PURPOSE_PROGRAM_REQUEST_NOTICE = "program_request_notice"
PURPOSE_MODEL_SPEND_ALERT = "model_spend_alert"
PURPOSE_OWNER_LOGIN_ALERT = "owner_login_alert"
PURPOSE_ACCOUNT_DELETED = "account_deleted"


@dataclass(frozen=True)
class DeliveryContext:
    purpose: str
    account_id: str | None = None
    recipient_email: str | None = None


def _reset_link_base_url() -> str:
    """The base for reset links, defaulting to the API's own local base.

    ``RESET_LINK_BASE_URL`` must be the public host that serves both
    ``/reset-password`` and ``/.well-known/assetlinks.json``. There is no
    ``UI_BASE_URL`` fallback: the legacy Streamlit UI does not serve the reset
    path (ADR 037). The localhost default is for development only.
    """
    return os.getenv("RESET_LINK_BASE_URL", "http://localhost:8000").rstrip("/")


def build_reset_link(token: str) -> str:
    """Builds the reset link as ``<base>/reset-password?token=<token>``.

    The path is an https Android App Link when installed, and the API's hosted
    fallback page otherwise. The legacy ``?reset_token=`` Streamlit link was
    retired with the Streamlit client (ADR 017/022/037).
    """
    return f"{_reset_link_base_url()}/reset-password?token={token}"


def _recipient_reference(delivery: DeliveryContext) -> str | None:
    if delivery.account_id:
        return f"account:{delivery.account_id}"
    if not delivery.recipient_email:
        return None
    secret = os.getenv("JWT_SECRET", "").encode()
    key = hmac.new(secret, b"email-log-ref", hashlib.sha256).digest() if secret else _FALLBACK_EMAIL_HASH_KEY
    digest = hmac.new(key, delivery.recipient_email.strip().lower().encode(), hashlib.sha256).hexdigest()[:16]
    return f"email:{digest}"


def _smtp_code(error: Exception) -> str:
    smtp_code = getattr(error, "smtp_code", None)
    if isinstance(smtp_code, int):
        return str(smtp_code)
    rejected = getattr(error, "recipients", None)
    if isinstance(rejected, dict):
        codes = {
            details[0]
            for details in rejected.values()
            if isinstance(details, tuple) and details and isinstance(details[0], int)
        }
        if len(codes) == 1:
            return str(next(iter(codes)))
        if codes:
            return "multiple"
    return "unavailable"


def log_delivery_failure(delivery: DeliveryContext, error: Exception) -> None:
    details = [f"purpose={delivery.purpose}"]
    recipient_ref = _recipient_reference(delivery)
    if recipient_ref:
        details.append(f"recipient_ref={recipient_ref}")
    details.extend((f"error_class={type(error).__name__}", f"smtp_code={_smtp_code(error)}"))
    logger.error("Email delivery failed %s", " ".join(details))


def log_email_preparation_failure(delivery: DeliveryContext, error: Exception) -> None:
    details = [f"purpose={delivery.purpose}"]
    if delivery.account_id:
        details.append(f"account_id={delivery.account_id}")
    details.append(f"error_class={type(error).__name__}")
    logger.exception(
        "Could not prepare email %s",
        " ".join(details),
        exc_info=(type(error), error, error.__traceback__),
    )


def _console_send(
    to_email: str, subject: str, body: str, delivery: DeliveryContext
) -> bool:
    safe_body = _EMAIL_ADDRESS_TOKEN.sub("[redacted email]", body)
    details = [f"purpose={delivery.purpose}"]
    recipient_ref = _recipient_reference(delivery)
    if recipient_ref:
        details.append(f"recipient_ref={recipient_ref}")
    logger.info("CONSOLE email backend: %s subject=%s\n%s", " ".join(details), subject, safe_body)
    return True


def _deliver(
    to_email: str,
    subject: str,
    body: str,
    *,
    delivery: DeliveryContext,
) -> bool:
    """Sends via SMTP when configured, otherwise logs the message (console backend).

    Never raises: a transport failure is logged and reported as ``False`` so callers
    can keep a generic response and never roll back committed state.
    """
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if not smtp_host:
        return _console_send(to_email, subject, body, delivery)
    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = os.getenv("SMTP_FROM", "no-reply@mayos.local")
        message["To"] = to_email
        message.set_content(body)
        port = int(os.getenv("SMTP_PORT", "587"))
        context = ssl.create_default_context()
        use_tls = env_flag("SMTP_USE_TLS", True)
        if use_tls:
            with smtplib.SMTP(smtp_host, port, timeout=10) as server:
                server.starttls(context=context)
                username = os.getenv("SMTP_USER", "")
                if username:
                    server.login(username, os.getenv("SMTP_PASSWORD", ""))
                server.send_message(message)
        else:
            with smtplib.SMTP_SSL(smtp_host, port, timeout=10, context=context) as server:
                username = os.getenv("SMTP_USER", "")
                if username:
                    server.login(username, os.getenv("SMTP_PASSWORD", ""))
                server.send_message(message)
        return True
    except Exception as exc:
        log_delivery_failure(delivery, exc)
        return False


def send_assignment_redemption_email(
    to_email: str,
    coach_display_name: str,
    player_username: str,
    *,
    account_id: str | None = None,
) -> bool:
    """Generic coach notice that an invite was redeemed. Deliberately contains no training data.

    The player's username is identity, not training detail, and is included so the
    coach can detect an unintended redemption (ADR 014). The code itself is never
    included and never logged.
    """
    subject = "A player accepted your MAYOS coaching invite"
    body = (
        f"Hi {coach_display_name},\n\n"
        f"{player_username} accepted your coaching invite and is now assigned to you.\n\n"
        "Open MAYOS to review the assignment. If you did not expect this, you can revoke "
        "the assignment immediately.\n\n"
        "This notice does not include any training data."
    )
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_ASSIGNMENT_NOTICE, account_id, to_email),
    )


def send_program_request_email(
    to_email: str,
    coach_display_name: str,
    player_username: str,
    *,
    account_id: str | None = None,
) -> bool:
    """Generic coach notice that a player requested a program change.

    Deliberately contains no training data: no exercise, day, slot, or requested
    replacement is ever named. The player's username is identity, not training
    detail, and is included so the coach can act on the request.
    """
    subject = "A player requested a program change"
    body = (
        f"Hi {coach_display_name},\n\n"
        f"{player_username} requested a program change. Review it in your roster.\n\n"
        "This notice does not include any training data."
    )
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_PROGRAM_REQUEST_NOTICE, account_id, to_email),
    )


def send_model_spend_alert_email(
    to_email: str, projected_usd: float, actual_usd: float, threshold_usd: float
) -> bool:
    """Owner-only notice that projected hosted-model spend crossed the trial threshold (ADR 038).

    Contains aggregate spend figures only — never account ids, prompts, or any
    player/coach content. The owner reviews per-account usage with
    ``scripts/model_usage_report.py``.
    """
    subject = "MAYOS model spend alert"
    body = (
        "Hosted model spend for the closed trial has crossed the alert threshold.\n\n"
        f"Threshold:        ${threshold_usd:,.2f}\n"
        f"Projected month:  ${projected_usd:,.2f}\n"
        f"Month-to-date:    ${actual_usd:,.2f}\n\n"
        "Review actual usage before expanding:\n"
        "  python scripts/model_usage_report.py\n\n"
        "This notice contains aggregate spend only."
    )
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_MODEL_SPEND_ALERT, recipient_email=to_email),
    )


def send_owner_login_alert_email(to_email: str, login_time: str, source_ip: str, user_agent: str) -> bool:
    """Alerts the owner to an admin login without including credentials or account data."""
    subject = "MAYOS owner dashboard login"
    body = (
        "The MAYOS owner dashboard was accessed successfully.\n\n"
        f"Time (UTC): {login_time}\n"
        f"IP address: {_single_line(source_ip)}\n"
        f"User agent: {_single_line(user_agent)}\n"
    )
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_OWNER_LOGIN_ALERT, recipient_email=to_email),
    )


def _single_line(value: str) -> str:
    return " ".join(str(value).split())[:500] or "unavailable"


def send_password_reset_email(
    to_email: str, reset_link: str, *, account_id: str | None = None
) -> bool:
    # Local import: password_reset imports this module, so a top-level import
    # here would be circular. The TTL stays defined in one place.
    from service.password_reset import reset_ttl

    minutes = max(1, int(reset_ttl().total_seconds() // 60))
    subject = "Mayos Engine password reset"
    body = (
        "A password reset was requested for your Mayos training ledger.\n\n"
        "Open this link to set a new password. If the MAYOS app is installed it "
        "opens the app; otherwise it opens a secure web page.\n\n"
        f"{reset_link}\n\n"
        f"This link is single-use and expires in {minutes} minutes.\n\n"
        "If you did not request this, ignore this message — your password is unchanged."
    )
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_PASSWORD_RESET, account_id, to_email),
    )


def send_account_deleted_email(
    to_email: str, username: str, *, account_id: str | None = None
) -> bool:
    """Notifies the account holder that the owner permanently deleted it."""
    subject = "Your MAYOS account was deleted at your request"
    body = (
        f"Hi {username},\n\n"
        "Your MAYOS account was deleted at your request. This deletion is final.\n"
    )
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_ACCOUNT_DELETED, account_id, to_email),
    )
