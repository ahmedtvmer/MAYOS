"""Temporary HTTP/API harness for the Program import evaluation runner."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

_JWT_SECRET = "program-import-eval-secret-0123456789"
_EXERCISE_TABLES = {
    "exercise_aliases",
    "exercise_curated_fields",
    "exercise_display_names",
    "exercise_embedding_sources",
    "exercise_provenance",
    "exercise_secondary_muscles",
    "exercises",
}


def _clear_catalog_registry_rows(connection: Any) -> None:
    connection.execute("DROP TRIGGER IF EXISTS audit_log_no_recent_delete")
    tables = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        with connection:
            for (table_name,) in tables:
                if (
                    table_name in _EXERCISE_TABLES
                    or table_name.startswith("vec_exercises")
                    or table_name == "sqlite_sequence"
                ):
                    continue
                quoted_name = table_name.replace('"', '""')
                connection.execute(f'DELETE FROM "{quoted_name}"')
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


class ProgramImportEvaluationSession:
    """Owns a temporary catalog copy, empty ledgers, and a real TestClient seam."""

    _ENV = {
        "SKIP_LLM_LOAD": "true",
        "TESTING": "1",
        "JWT_SECRET": _JWT_SECRET,
        "POSTHOG_API_KEY": "",
        "PROGRAM_IMPORT_AI_ENABLED": "false",
        "PROGRAM_IMPORT_AI_EVAL_REPORT": "",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "SMTP_HOST": "",
        "SMTP_PORT": "",
        "SMTP_USE_TLS": "",
        "SMTP_USER": "",
        "SMTP_PASSWORD": "",
        "SMTP_FROM": "",
    }

    def __init__(self):
        self._environment: dict[str, str | None] = {}
        self._previous_cwd: str | None = None
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._previous_coach_model: Any = None
        self.db: Any = None
        self.client: Any = None
        self.coach_headers: dict[str, str] = {}
        self.assignment_id = ""

    def __enter__(self) -> ProgramImportEvaluationSession:
        self._environment = {key: os.environ.get(key) for key in self._ENV}
        os.environ.update(self._ENV)
        self._temporary = tempfile.TemporaryDirectory(prefix="program-import-eval-")
        self._previous_cwd = os.getcwd()
        os.chdir(self._temporary.name)
        try:
            from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager
            from fastapi.testclient import TestClient
            from service import coach as coach_service
            from svc.app import create_app
            from svc.dependencies import get_db
            from svc.rate_limit import limiter

            catalog_path = Path(self._temporary.name) / "catalog.db"
            source_catalog = Path(DEFAULT_CATALOG_PATH)
            if not source_catalog.is_file():
                raise RuntimeError(f"seeded Exercise library is unavailable: {source_catalog}")
            shutil.copyfile(source_catalog, catalog_path)
            self.db = DatabaseManager(
                catalog_path=catalog_path,
                ledgers_dir=Path(self._temporary.name) / "users",
                backups_dir=Path(self._temporary.name) / "backups",
                default_ledger_id="program-import-evaluation",
            )
            _clear_catalog_registry_rows(self.db.catalog_conn)
            limiter._storage.reset()
            app = create_app()
            app.dependency_overrides[get_db] = lambda: self.db
            self.client = TestClient(app)
            self.client.__enter__()
            self._create_assignment(coach_service)
            from utils import model_downloader

            self._previous_coach_model = model_downloader._coach_llm_instance
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _register(self, username: str) -> dict[str, str]:
        response = self.client.post(
            "/auth/register",
            json={"trainee_id": username, "password": "correct-horse-1"},
        )
        if response.status_code != 201:
            raise RuntimeError(f"temporary evaluation account registration failed: {response.text}")
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def _create_assignment(self, coach_service: Any) -> None:
        self.coach_headers = self._register("program-import-eval-coach")
        invite = coach_service.issue_coach_invite(self.db, "program-import-eval-coach", actor="cli")
        if not invite.get("ok"):
            raise RuntimeError("could not create the temporary evaluation Coach")
        redeemed = self.client.post(
            "/coach/invite/redeem",
            headers=self.coach_headers,
            json={"token": invite["token"]},
        )
        if redeemed.status_code != 200:
            raise RuntimeError(f"temporary Coach setup failed: {redeemed.text}")
        profile = self.client.put(
            "/coach/profile",
            headers=self.coach_headers,
            json={"display_name": "Synthetic evaluation Coach", "bio": "", "specialization": "", "capacity": 5},
        )
        if profile.status_code != 200:
            raise RuntimeError(f"temporary Coach profile setup failed: {profile.text}")
        player_headers = self._register("program-import-eval-player")
        assignment_invite = self.client.post("/coach/assignments/invites", headers=self.coach_headers)
        if assignment_invite.status_code != 200:
            raise RuntimeError(f"temporary Assignment invite failed: {assignment_invite.text}")
        redeemed_assignment = self.client.post(
            "/assignments/invites/redeem",
            headers=player_headers,
            json={"token": assignment_invite.json()["token"], "consent": True},
        )
        if redeemed_assignment.status_code != 200:
            raise RuntimeError(f"temporary Assignment setup failed: {redeemed_assignment.text}")
        self.assignment_id = redeemed_assignment.json()["assignment"]["assignment_id"]

    def import_case(self, case: dict[str, Any], selected_tab: str | None = None):
        from tests.eval.run_program_import_evaluation import spreadsheet_bytes as _spreadsheet_bytes

        filename = f"{case['id']}.{case['format']}"
        mime_type = (
            "text/csv"
            if case["format"] == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        data = {"sheet": selected_tab} if selected_tab else None
        return self.client.post(
            f"/coach/assignments/{self.assignment_id}/program-import",
            headers=self.coach_headers,
            files={"file": (filename, _spreadsheet_bytes(case), mime_type)},
            data=data,
        )

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if self.client is not None:
                self.client.__exit__(exc_type, exc, traceback)
                self.client = None
            if self.db is not None:
                self.db.catalog_conn.close()
                self.db = None
        finally:
            from utils import model_downloader

            model_downloader._coach_llm_instance = self._previous_coach_model
            if self._previous_cwd is not None:
                os.chdir(self._previous_cwd)
                self._previous_cwd = None
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None
            for key, value in self._environment.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            self._environment = {}
