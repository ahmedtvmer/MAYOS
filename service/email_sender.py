"""Outbound email for account recovery and assignment notices.

Production delivery requires SMTP_* env (see .env.example). When SMTP_HOST is
unset, the message is logged server-side instead of sent — safe for local dev,
never for shared hosting. This module never raises for transport issues; callers
log the boolean and keep generic client responses.
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def _ui_base_url() -> str:
    return os.getenv("UI_BASE_URL", "http://localhost:8501").rstrip("/")


def build_reset_link(token: str) -> str:
    return f"{_ui_base_url()}/?reset_token={token}"


def _console_send(to_email: str, subject: str, body: str) -> bool:
    logger.info("CONSOLE email backend: to=%s subject=%s\n%s", to_email, subject, body)
    return True


def _deliver(to_email: str, subject: str, body: str) -> bool:
    """Sends via SMTP when configured, otherwise logs the message (console backend).

    Never raises: a transport failure is logged and reported as ``False`` so callers
    can keep a generic response and never roll back committed state.
    """
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if not smtp_host:
        return _console_send(to_email, subject, body)
    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = os.getenv("SMTP_FROM", "no-reply@mayos.local")
        message["To"] = to_email
        message.set_content(body)
        port = int(os.getenv("SMTP_PORT", "587"))
        context = ssl.create_default_context()
        use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}
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
    except Exception:
        logger.exception("Email delivery failed for %s", to_email)
        return False


def send_assignment_redemption_email(to_email: str, coach_display_name: str, player_username: str) -> bool:
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
    return _deliver(to_email, subject, body)


def send_password_reset_email(to_email: str, reset_link: str) -> bool:
    subject = "Mayos Engine password reset"
    body = (
        "A password reset was requested for your Mayos training ledger.\n\n"
        f"Reset link (valid briefly, single-use):\n{reset_link}\n\n"
        "If you did not request this, ignore this message — your password is unchanged."
    )
    return _deliver(to_email, subject, body)
