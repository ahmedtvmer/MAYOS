import logging
import sqlite3

import pytest

from database.database_manager import DatabaseManager
from scripts import announce_move


def _build_catalog(tmp_path):
    catalog_path = tmp_path / "catalog.db"
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    account_ids = {}
    for username, language, email, verified, deleted in (
        ("english-player", "en", "english@example.com", True, False),
        ("arabic-coach", "ar", "arabic@example.com", True, False),
        ("unverified-player", "en", "unverified@example.com", False, False),
        ("deleted-player", "en", "deleted@example.com", True, True),
    ):
        account_id = db.create_account(username, display_language=language)
        assert account_id is not None
        account_ids[username] = account_id
        db.set_account_email(account_id, email)
        with db.catalog_transaction():
            db.catalog_conn.execute(
                "UPDATE trainee_emails SET verified = ? WHERE trainee_id = ?",
                (int(verified), account_id),
            )
            if deleted:
                db.catalog_conn.execute(
                    "UPDATE accounts SET status = 'deleted', deleted_at = '2026-10-07' WHERE account_id = ?",
                    (account_id,),
                )
            if username == "arabic-coach":
                db.catalog_conn.execute(
                    "UPDATE accounts SET is_player = 0, is_coach = 1 WHERE account_id = ?",
                    (account_id,),
                )
    db.catalog_conn.close()
    return catalog_path, account_ids


def _catalog_args(catalog_path, tmp_path):
    return [
        "--catalog",
        str(catalog_path),
        "--users-dir",
        str(tmp_path / "users"),
        "--backups-dir",
        str(tmp_path / "backups"),
    ]


def test_dry_run_lists_verified_live_recipients_and_previews_both_languages(
    tmp_path, monkeypatch, caplog, capsys
):
    catalog_path, _account_ids = _build_catalog(tmp_path)
    monkeypatch.setenv("SMTP_HOST", "")

    with caplog.at_level(logging.INFO, logger="service.email_sender"):
        exit_code = announce_move.main(
            _catalog_args(catalog_path, tmp_path)
            + [
                "--template",
                "update-required",
                "--move-date",
                "2026-11-03",
                "--play-url",
                "https://play.google.com/store/apps/details?id=com.mayos.mayos_mobile",
                "--dry-run",
            ]
        )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Recipients: 2" in output
    assert "English: 1" in output
    assert "Arabic: 1" in output
    assert "MAYOS is moving to a faster server on 2026-11-03." in output
    assert "2026-11-03" in output
    assert "https://play.google.com/store/apps/details?id=com.mayos.mayos_mobile" in output
    assert "MAYOS هيتنقل على سيرفر أسرع" in output
    assert "من فضلك حدّث التطبيق" in output
    assert "CONSOLE email backend" not in caplog.text


def test_send_delivers_each_verified_account_in_its_language_and_audits_run(
    tmp_path, monkeypatch, caplog, capsys
):
    catalog_path, account_ids = _build_catalog(tmp_path)
    monkeypatch.setenv("SMTP_HOST", "")

    with caplog.at_level(logging.INFO, logger="service.email_sender"):
        exit_code = announce_move.main(
            _catalog_args(catalog_path, tmp_path)
            + ["--template", "move-day", "--window", "2026-11-03 08:00–10:00 Cairo time", "--send"]
        )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert caplog.text.count("CONSOLE email backend:") == 2
    assert "MAYOS move-day service notice" in caplog.text
    assert "MAYOS هيقف مؤقتًا يوم النقل" in caplog.text
    assert "2026-11-03 08:00–10:00 Cairo time" in caplog.text
    assert "Recipients: 2" in output
    assert "english@example.com" not in caplog.text
    assert "arabic@example.com" not in caplog.text

    with sqlite3.connect(catalog_path) as conn:
        audit = conn.execute(
            "SELECT actor, action, target_account_id, reason FROM audit_log"
        ).fetchone()
    assert audit == (
        "cli",
        "announcement_email_run",
        None,
        "template=move-day; recipients=2; sent=2; failed=0",
    )
    assert account_ids["deleted-player"] not in caplog.text

    assert account_ids["english-player"] in caplog.text
    assert account_ids["arabic-coach"] in caplog.text
    assert account_ids["unverified-player"] not in caplog.text


def test_missing_template_parameter_is_usage_error_before_database_open(capsys):
    with pytest.raises(SystemExit) as exc_info:
        announce_move.main(["--template", "update-required", "--send"])

    assert exc_info.value.code == 2
    assert "--move-date is required" in capsys.readouterr().err
