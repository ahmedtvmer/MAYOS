import hashlib
import hmac
import logging
import smtplib

from service import email_sender


def test_issue_176_smtp_failure_omits_recipient_and_keeps_diagnostics(monkeypatch, caplog):
    recipient = "private.player@example.com"

    class FailingSMTP:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self, **_kwargs):
            return None

        def send_message(self, _message):
            raise smtplib.SMTPRecipientsRefused(
                {recipient: (550, f"5.1.1 recipient {recipient} rejected".encode())}
            )

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setattr(email_sender.smtplib, "SMTP", lambda *_args, **_kwargs: FailingSMTP())

    with caplog.at_level(logging.ERROR, logger="service.email_sender"):
        delivered = email_sender.send_password_reset_email(
            recipient,
            "https://mayos.example/reset-password?token=secret-token",
            account_id="account-123",
        )

    assert delivered is False
    assert recipient not in caplog.text
    assert "purpose=password_reset" in caplog.text
    assert "account-123" in caplog.text
    assert "smtp_code=550" in caplog.text


def test_issue_176_console_log_uses_keyed_recipient_reference(monkeypatch, caplog):
    recipient = "private.player@example.com"
    secret = "test-secret"
    key = hmac.new(secret.encode(), b"email-log-ref", hashlib.sha256).digest()
    digest = hmac.new(key, recipient.encode(), hashlib.sha256).hexdigest()[:16]
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("JWT_SECRET", secret)

    with caplog.at_level(logging.INFO, logger="service.email_sender"):
        email_sender.send_password_reset_email(
            recipient,
            f"https://mayos.example/reset-password?token=secret-token&address={recipient}",
        )

    assert recipient not in caplog.text
    assert f"recipient_ref=email:{digest}" in caplog.text
    assert "https://mayos.example/reset-password?token=secret-token&address=[redacted email]" in caplog.text


def test_no_account_notice_uses_console_sender_without_personal_details(monkeypatch, caplog):
    recipient = "private.player@example.com"
    monkeypatch.setenv("SMTP_HOST", "")

    with caplog.at_level(logging.INFO, logger="service.email_sender"):
        delivered = email_sender.send_no_account_notice_email(
            recipient, "https://mayos.example/register"
        )

    assert delivered is True
    assert "No MAYOS account uses this email" in caplog.text
    assert "https://mayos.example/register" in caplog.text
    assert "try the email address you registered with" in caplog.text
    assert "log in and add a recovery email in Settings" in caplog.text
    assert recipient not in caplog.text


def test_coach_invite_console_sender_never_logs_the_code_or_recovery_email(monkeypatch, caplog):
    recipient = "private.player@example.com"
    code = "one-time-coach-code"
    monkeypatch.setenv("SMTP_HOST", "")

    with caplog.at_level(logging.INFO, logger="service.email_sender"):
        delivered = email_sender.send_coach_invite_email(
            recipient, code, "en", account_id="account-coach-invite"
        )

    assert delivered is True
    assert code not in caplog.text
    assert recipient not in caplog.text
    assert "[redacted one-time coach invite code]" in caplog.text


def test_email_reference_and_notice_keys_are_purpose_separated_without_secret(monkeypatch):
    from service.email_hash_keys import derive_email_hash_key

    monkeypatch.delenv("JWT_SECRET", raising=False)

    assert derive_email_hash_key("log-ref") != derive_email_hash_key(
        "no-account-notice"
    )
