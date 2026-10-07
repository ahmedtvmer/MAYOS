"""One-off owner announcements for the server move (ADR 072, ticket #373).

Usage:
    python scripts/announce_move.py --template update-required --move-date 2026-11-03 --dry-run
    python scripts/announce_move.py --template move-day --window "2026-11-03 08:00–10:00 Cairo time" --send
"""

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import (  # noqa: E402
    DEFAULT_BACKUPS_DIR,
    DEFAULT_CATALOG_PATH,
    DEFAULT_LEDGERS_DIR,
    DatabaseManager,
)
from service import audit_log, email_sender  # noqa: E402
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)
DEFAULT_PLAY_URL = "https://play.google.com/store/apps/details?id=com.mayos.mayos_mobile"

TEMPLATES = {
    "update-required": {
        "en": {
            "subject": "Please update MAYOS before the move",
            "body": (
                "Hello,\n\n"
                "MAYOS is moving to a faster server on {move_date}. Please update the app before then "
                "to keep using MAYOS. You can download the latest version here:\n{play_url}\n\n"
                "Thank you,\nThe MAYOS team"
            ),
        },
        "ar": {
            "subject": "حدّث MAYOS قبل النقل",
            "body": (
                "أهلاً،\n\n"
                "MAYOS هيتنقل على سيرفر أسرع يوم {move_date}. من فضلك حدّث التطبيق قبل اليوم ده "
                "عشان تفضل تستخدم MAYOS من غير مشاكل. تقدر تنزّل آخر إصدار من هنا:\n{play_url}\n\n"
                "شكرًا،\nفريق MAYOS"
            ),
        },
    },
    "move-day": {
        "en": {
            "subject": "MAYOS move-day service notice",
            "body": (
                "Hello,\n\n"
                "MAYOS is moving to a faster server{date_phrase}. The service will be unavailable "
                "during this window: {window}. Workouts you log in the Android app during this time stay saved "
                "on your phone and sync automatically once MAYOS is back.\n\n"
                "Thank you,\nThe MAYOS team"
            ),
        },
        "ar": {
            "subject": "MAYOS هيقف مؤقتًا يوم النقل",
            "body": (
                "أهلاً،\n\n"
                "MAYOS بيتنقل على سيرفر أسرع{date_phrase}. الخدمة هتكون واقفة في الفترة دي: {window}. "
                "الحصص التدريبية اللي هتسجّلها على تطبيق Android في الوقت ده هتفضل محفوظة على موبايلك، "
                "وهتتزامن لوحدها أول ما MAYOS يرجع.\n\n"
                "شكرًا،\nفريق MAYOS"
            ),
        },
    },
}


@dataclass(frozen=True)
class AnnouncementRequest:
    template: str
    mode: str
    move_date: str | None
    window: str | None
    play_url: str


@dataclass(frozen=True)
class AnnouncementRecipient:
    account_id: str
    email: str
    language: str


def _eligible_recipients(db: DatabaseManager) -> list[AnnouncementRecipient]:
    recipients = []
    for account in db.list_accounts():
        if not (account["is_player"] or account["is_coach"]):
            continue
        account_id = account["account_id"]
        if not db.is_recovery_email_verified(account_id):
            continue
        email = db.get_account_email(account_id)
        if email:
            language = account["display_language"] if account["display_language"] in ("en", "ar") else "en"
            recipients.append(AnnouncementRecipient(account_id, email, language))
    return recipients


def _render_email(request: AnnouncementRequest, language: str) -> tuple[str, str]:
    template = TEMPLATES[request.template][language]
    date_phrase = ""
    if request.move_date is not None:
        date_phrase = f" on {request.move_date}" if language == "en" else f" يوم {request.move_date}"
    values = {
        "move_date": request.move_date or "",
        "date_phrase": date_phrase,
        "window": request.window or "",
        "play_url": request.play_url,
    }
    return template["subject"], template["body"].format(**values)


def _print_summary(recipients: list[AnnouncementRecipient]) -> None:
    language_counts = {language: sum(recipient.language == language for recipient in recipients) for language in ("en", "ar")}
    print(f"Recipients: {len(recipients)}")
    print(f"English: {language_counts['en']}")
    print(f"Arabic: {language_counts['ar']}")


def _print_previews(request: AnnouncementRequest) -> None:
    for language, label in (("en", "English"), ("ar", "Arabic")):
        subject, body = _render_email(request, language)
        print(f"\n--- {label} preview ---")
        print(f"Subject: {subject}\n\n{body}")


def _deliver_recipients(
    request: AnnouncementRequest,
    recipients: list[AnnouncementRecipient],
    rendered: dict[str, tuple[str, str]],
) -> tuple[int, int]:
    sent = 0
    failed = 0
    for recipient in recipients:
        subject, body = rendered[recipient.language]
        delivered = email_sender.send_announcement_email(recipient.email, subject, body, account_id=recipient.account_id)
        if delivered:
            sent += 1
            logger.info("Announcement email sent account_id=%s template=%s", recipient.account_id, request.template)
        else:
            failed += 1
            logger.error("Announcement email failed account_id=%s template=%s", recipient.account_id, request.template)
    return sent, failed


def _send_announcements(db: DatabaseManager, request: AnnouncementRequest, recipients: list[AnnouncementRecipient]) -> int:
    rendered = {language: _render_email(request, language) for language in ("en", "ar")}
    sent, failed = _deliver_recipients(request, recipients, rendered)
    reason = f"template={request.template}; recipients={len(recipients)}; sent={sent}; failed={failed}"
    try:
        audit_log.write_audit_entry(db, audit_log.AuditEvent(actor="cli", action="announcement_email_run", reason=reason))
    except sqlite3.Error as exc:
        logger.error("Announcement audit entry failed error_class=%s", type(exc).__name__)
        print("error: announcement emails were processed, but the admin audit entry could not be written.", file=sys.stderr)
        return 1

    print(f"Sent: {sent}; failed: {failed}")
    return 1 if failed else 0


def _request_from_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> AnnouncementRequest:
    if args.template == "update-required" and not (args.move_date and args.move_date.strip()):
        parser.error("--move-date is required for update-required.")
    if args.template == "move-day" and not (args.window and args.window.strip()):
        parser.error("--window is required for move-day.")
    if args.template == "update-required" and not args.play_url.strip():
        parser.error("--play-url must not be empty.")
    return AnnouncementRequest(
        template=args.template,
        mode="dry-run" if args.dry_run else "send",
        move_date=args.move_date,
        window=args.window,
        play_url=args.play_url,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send or preview MAYOS move announcements.")
    parser.add_argument("--template", choices=tuple(TEMPLATES), required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Print recipient counts and rendered previews without sending.")
    mode.add_argument("--send", action="store_true", help="Send one private email per eligible Account.")
    parser.add_argument("--move-date", help="Move date shown in the update-required and optional move-day email.")
    parser.add_argument("--window", help="Move-day downtime window, including its timezone.")
    parser.add_argument("--play-url", default=DEFAULT_PLAY_URL, help="Google Play URL for the update-required email.")
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument("--users-dir", dest="ledgers_dir", default=os.getenv("USERS_DIR", str(DEFAULT_LEDGERS_DIR)))
    parser.add_argument("--backups-dir", default=os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)))
    return parser


def _run_request(db: DatabaseManager, request: AnnouncementRequest) -> int:
    recipients = _eligible_recipients(db)
    _print_summary(recipients)
    if request.mode == "dry-run":
        _print_previews(request)
        return 0
    return _send_announcements(db, request, recipients)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    request = _request_from_args(parser, args)
    db = DatabaseManager(catalog_path=args.catalog, ledgers_dir=args.ledgers_dir, backups_dir=args.backups_dir)
    try:
        return _run_request(db, request)
    finally:
        db.catalog_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
