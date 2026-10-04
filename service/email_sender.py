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
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from service.email_hash_keys import derive_email_hash_key
from utils.env_flags import env_flag

logger = logging.getLogger(__name__)
_EMAIL_ADDRESS_TOKEN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+(?![A-Za-z0-9.-])"
)
_MASKED_EMAIL_TOKEN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]\*{2,}@[A-Za-z0-9.-]+"
)

PURPOSE_PASSWORD_RESET = "password_reset"
PURPOSE_COACH_INVITE = "coach_invite"
PURPOSE_RECOVERY_EMAIL_VERIFICATION = "recovery_email_verification"
PURPOSE_RECOVERY_EMAIL_CHANGED_NOTICE = "recovery_email_changed_notice"
PURPOSE_NO_ACCOUNT_NOTICE = "no_account_notice"
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
    ``UI_BASE_URL`` fallback. The localhost default is for development only.
    """
    return os.getenv("RESET_LINK_BASE_URL", "http://localhost:8000").rstrip("/")


def build_reset_link(token: str) -> str:
    """Builds the reset link as ``<base>/reset-password?token=<token>``.

    The path is an https Android App Link when installed, and the API's hosted
    fallback page otherwise. The reset path is served by the API and the Flutter app.
    """
    return f"{_reset_link_base_url()}/reset-password?token={token}"


def build_signup_link() -> str:
    """Builds a signup link on the same host as reset links."""
    return f"{_reset_link_base_url()}/register"


def _recipient_reference(delivery: DeliveryContext) -> str | None:
    if delivery.account_id:
        return f"account:{delivery.account_id}"
    if not delivery.recipient_email:
        return None
    digest = hmac.new(
        derive_email_hash_key("log-ref"),
        delivery.recipient_email.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]
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
    safe_body = _MASKED_EMAIL_TOKEN.sub("[redacted email]", safe_body)
    details = [f"purpose={delivery.purpose}"]
    recipient_ref = _recipient_reference(delivery)
    if recipient_ref:
        details.append(f"recipient_ref={recipient_ref}")
    if delivery.purpose == PURPOSE_COACH_INVITE:
        safe_body = "[redacted one-time coach invite code]"
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


def send_coach_invite_email(
    to_email: str,
    code: str,
    display_language: str,
    *,
    account_id: str | None = None,
) -> bool:
    """Sends an account-bound Coach invite in the recipient's Display language."""
    subject, body = _coach_invite_copy(code, display_language)
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_COACH_INVITE, account_id, to_email),
    )


def _coach_invite_copy(code: str, display_language: str) -> tuple[str, str]:
    if display_language == "ar":
        return (
            "دعوة تفعيل دور المدرب في MAYOS",
            "تمت دعوتك لتفعيل دور المدرب في حسابك على MAYOS.\n\n"
            f"رمز دعوة تفعيل دور المدرب:\n{code}\n\n"
            "سجّل الدخول إلى تطبيق MAYOS، ثم افتح الإعدادات واختر «كن مدربًا» وأدخل هذا الرمز. "
            "يفعّل الرمز وضع المدرب في حسابك، ولا ينشئ علاقة تدريب. يمكن استخدامه مرة واحدة.\n\n"
            "إذا لم تكن تتوقع هذه الدعوة، فتجاهل هذه الرسالة."
        )
    return (
        "Your MAYOS Coach invite",
        "You have been invited to enable Coach capability on your MAYOS account.\n\n"
        f"Coach invite code:\n{code}\n\n"
        "Sign in to the MAYOS app, open Settings, choose “Become a coach”, and enter this code. "
        "It enables Coach mode on your account and does not create an Assignment. "
        "This code can be used once.\n\n"
        "If you were not expecting this invite, ignore this email."
    )


def send_recovery_email_verification_code(
    to_email: str,
    code: str,
    display_language: str,
    *,
    account_id: str | None = None,
) -> bool:
    """Sends a short-lived recovery-email code in the account's Display language."""
    from service.email_verification import verification_code_ttl

    minutes = max(1, int(verification_code_ttl().total_seconds() // 60))
    subject, body = _recovery_email_verification_copy(code, display_language, minutes)
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_RECOVERY_EMAIL_VERIFICATION, account_id, to_email),
    )


def send_recovery_email_changed_notice(
    to_email: str,
    masked_new_email: str,
    display_language: str,
    *,
    account_id: str | None = None,
) -> bool:
    """Notifies the previous address after a verified recovery-email swap."""
    subject, body = _recovery_email_changed_notice_copy(
        masked_new_email, display_language
    )
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_RECOVERY_EMAIL_CHANGED_NOTICE, account_id, to_email),
    )


def _recovery_email_changed_notice_copy(
    masked_new_email: str, display_language: str
) -> tuple[str, str]:
    if display_language == "ar":
        subject = "تم تغيير البريد الإلكتروني للاسترداد في MAYOS"
        body = (
            "تم تغيير البريد الإلكتروني للاسترداد لحساب MAYOS الخاص بك.\n\n"
            f"العنوان الجديد: \u2066{masked_new_email}\u2069\n\n"
            "إذا لم تطلب هذا التغيير، فأمّن حسابك بتغيير كلمة المرور."
        )
    else:
        subject = "Your MAYOS recovery email was changed"
        body = (
            "The recovery email for your MAYOS account was changed.\n\n"
            f"New address: {masked_new_email}\n\n"
            "If you did not make this change, secure your account by changing your password."
        )
    return subject, body


def _recovery_email_verification_copy(
    code: str, display_language: str, minutes: int
) -> tuple[str, str]:
    if display_language == "ar":
        subject = "رمز تأكيد البريد الإلكتروني للاسترداد في MAYOS"
        body = (
            "استخدم الرمز التالي لتأكيد بريدك الإلكتروني للاسترداد في MAYOS:\n\n"
            f"{code}\n\n"
            f"هذا الرمز صالح لمدة {minutes} دقائق ويُستخدم مرة واحدة. إذا لم تطلبه، فتجاهل هذه الرسالة."
        )
    else:
        subject = "Verify your MAYOS recovery email"
        body = (
            "Enter this code in MAYOS to verify your recovery email:\n\n"
            f"{code}\n\n"
            f"This single-use code expires in {minutes} minutes. If you did not request it, ignore this email."
        )
    return subject, body


def send_no_account_notice_email(to_email: str, signup_link: str) -> bool:
    """Tells an inbox owner how to proceed without naming any account details."""
    subject = "No MAYOS account uses this email"
    body = (
        "No MAYOS account uses this email.\n\n"
        f"You can sign up at {signup_link}.\n\n"
        "If you already have an account, try the email address you registered "
        "with, or log in and add a recovery email in Settings."
    )
    return _deliver(
        to_email,
        subject,
        body,
        delivery=DeliveryContext(PURPOSE_NO_ACCOUNT_NOTICE, recipient_email=to_email),
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
