"""SchemaMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import json
from typing import Any
from database.exercise_library.names import apply_curated_exercise_names
from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION
from database.migration_manager import EQUIPMENT_ACCESS_DDL
from database.migration_manager import CHECKPOINT_REVIEWS_DDL
from database.migration_manager import INTAKE_DDL
from database.migration_manager import PERFORMED_DATE_CORRECTIONS_DDL
from database.migration_manager import SESSION_CARDIO_DDL
from database.migration_manager import SESSION_WARMUP_SETS_DDL
from database.migration_manager import get_ledger_schema_version
from database.migration_manager import set_ledger_schema_version


class SchemaMixin:
    def _ensure_exercise_name_schema(self) -> None:
        with self._catalog_lock, self.catalog_conn:
            self.catalog_conn.execute("""
                CREATE TABLE IF NOT EXISTS exercise_display_names (
                    exercise_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    FOREIGN KEY(exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
                )
            """)
            self.catalog_conn.execute("""
                CREATE TABLE IF NOT EXISTS exercise_aliases (
                    exercise_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    PRIMARY KEY(exercise_id, normalized_alias),
                    FOREIGN KEY(exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
                )
            """)
            self.catalog_conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_exercise_alias_normalized
                ON exercise_aliases(normalized_alias)
            """)
            exercise_table_exists = self.catalog_conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'exercises'"
            ).fetchone()
            if exercise_table_exists is not None:
                apply_curated_exercise_names(self.catalog_conn.cursor())

    def create_catalog_schema(self) -> None:
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.executescript(f"""
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS exercises (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    body_part TEXT NOT NULL,
                    target_muscle TEXT NOT NULL,
                    equipment TEXT NOT NULL,
                    image_path TEXT,
                    gif_path TEXT,
                    instructions TEXT
                );
                CREATE TABLE IF NOT EXISTS exercise_secondary_muscles (
                    exercise_id TEXT NOT NULL,
                    muscle TEXT NOT NULL,
                    FOREIGN KEY(exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_exercises USING vec0(
                    exercise_id INTEGER PRIMARY KEY,
                    embedding float[{self.EMBEDDING_DIM}] distance_metric=cosine
                );
                CREATE INDEX IF NOT EXISTS idx_secondary_muscles_ex ON exercise_secondary_muscles(exercise_id);
            """)
            self.catalog_conn.commit()
        self._ensure_exercise_name_schema()
        # Outside the lock block: ensure_account_schema acquires _catalog_lock itself.
        self.ensure_account_schema()

    def _create_ledger_schema_on(self, conn) -> None:
        cursor = conn.cursor()
        cursor.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS user_profile (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                gender TEXT DEFAULT 'male',
                proportions TEXT NOT NULL,
                age INTEGER NOT NULL,
                weight_kg REAL NOT NULL,
                height_cm REAL NOT NULL,
                rep_preference TEXT DEFAULT 'balanced',
                current_goal TEXT NOT NULL,
                long_term_goal TEXT NOT NULL,
                weekly_frequency INTEGER NOT NULL,
                training_age_years REAL NOT NULL,
                equipment_access TEXT NOT NULL,
                injuries_or_limitations TEXT DEFAULT 'None',
                stress_and_sleep TEXT NOT NULL,
                coach_tone TEXT DEFAULT 'Direct, grounded, and pragmatic',
                custom_instructions TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auth_credentials (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                password_hash TEXT NOT NULL,
                token_version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS training_programs (
                id TEXT PRIMARY KEY,
                program_name TEXT NOT NULL,
                name TEXT NOT NULL,
                split_type TEXT NOT NULL,
                weekly_frequency INTEGER NOT NULL,
                instructions TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0,
                published_by_coach_account_id TEXT
            );
            CREATE TABLE IF NOT EXISTS program_days (
                id TEXT PRIMARY KEY,
                program_id TEXT NOT NULL,
                day_name TEXT NOT NULL,
                day_order INTEGER NOT NULL,
                warmup_json TEXT,
                cardio TEXT,
                FOREIGN KEY(program_id) REFERENCES training_programs(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS program_exercises (
                id TEXT PRIMARY KEY,
                day_id TEXT NOT NULL,
                exercise_id TEXT NOT NULL,
                order_in_day INTEGER NOT NULL,
                slot_key TEXT,
                warmup_sets INTEGER DEFAULT 0,
                target_sets INTEGER NOT NULL,
                target_reps_min INTEGER NOT NULL,
                target_reps_max INTEGER NOT NULL,
                target_rpe REAL,
                rest_seconds INTEGER DEFAULT 120,
                notes TEXT,
                FOREIGN KEY(day_id) REFERENCES program_days(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_program_days_prog ON program_days(program_id);
            CREATE INDEX IF NOT EXISTS idx_program_ex_day ON program_exercises(day_id);

            CREATE TABLE IF NOT EXISTS workout_sessions (
                id TEXT PRIMARY KEY,
                session_date TEXT NOT NULL,
                split_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                session_notes TEXT,
                readiness_score INTEGER CHECK(readiness_score BETWEEN 1 AND 5),
                coach_debrief TEXT,
                client_session_id TEXT,
                performed_timezone TEXT,
                program_version INTEGER,
                active_program_version_at_sync INTEGER,
                captured_at TEXT,
                uploaded_at TEXT,
                edited_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_workout_sessions_client
                ON workout_sessions(client_session_id) WHERE client_session_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS session_commits (
                client_session_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                response_json TEXT NOT NULL,
                committed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workout_sets (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                exercise_id TEXT NOT NULL,
                set_index INTEGER NOT NULL,
                weight_kg REAL NOT NULL,
                reps INTEGER NOT NULL,
                rpe REAL CHECK(rpe BETWEEN 1 AND 10),
                is_warmup INTEGER DEFAULT 0,
                logged_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS session_divergences (
                session_id TEXT NOT NULL,
                exercise_id TEXT NOT NULL,
                exercise_name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('skipped', 'unplanned')),
                created_at TEXT NOT NULL,
                PRIMARY KEY (session_id, exercise_id, kind),
                FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS personal_records (
                id TEXT PRIMARY KEY,
                exercise_id TEXT NOT NULL,
                record_type TEXT NOT NULL CHECK (record_type IN ('max_weight', 'max_e1rm')),
                reps INTEGER,
                value REAL NOT NULL,
                prev_value REAL,
                achieved_at TEXT NOT NULL,
                session_id TEXT,
                FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_pr_exercise ON personal_records(exercise_id, record_type);

            CREATE TABLE IF NOT EXISTS chat_history (
                id TEXT PRIMARY KEY,
                role TEXT CHECK(role IN ('user', 'assistant', 'system')) NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assistant_memory (
                key TEXT PRIMARY KEY CHECK (key = 'preferred_name'),
                value TEXT NOT NULL CHECK (length(value) BETWEEN 1 AND 60 AND length(trim(value)) > 0)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_history(created_at);
            CREATE INDEX IF NOT EXISTS idx_sets_session ON workout_sets(session_id);
            CREATE INDEX IF NOT EXISTS idx_sets_exercise ON workout_sets(exercise_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_date ON workout_sessions(session_date);

            CREATE TABLE IF NOT EXISTS training_schedules (
                id TEXT PRIMARY KEY,
                trainee_id TEXT NOT NULL,
                weekdays TEXT NOT NULL,
                timezone TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_training_schedules_trainee
                ON training_schedules(trainee_id, effective_from);
            CREATE TABLE IF NOT EXISTS training_pauses (
                id TEXT PRIMARY KEY,
                trainee_id TEXT NOT NULL,
                starts_on TEXT NOT NULL,
                ends_on TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_training_pauses_trainee ON training_pauses(trainee_id);

            CREATE TABLE IF NOT EXISTS engine_telemetry (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                route_intent TEXT NOT NULL,
                fast_path_latency_ms REAL,
                ttft_ms REAL,
                generation_ms REAL,
                token_count INTEGER,
                tps REAL,
                memory_rss_mb REAL
            );
            CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON engine_telemetry(timestamp);

            CREATE TABLE IF NOT EXISTS onboarding_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                intake_step INTEGER NOT NULL,
                is_complete INTEGER NOT NULL DEFAULT 0,
                profile_data TEXT,
                messages TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS revoked_tokens (
                jti TEXT PRIMARY KEY,
                expires_at TEXT NOT NULL,
                revoked_at TEXT NOT NULL
            );
        """ + "\n".join(
            f"{statement};"
            for statement in (
                *PERFORMED_DATE_CORRECTIONS_DDL,
                *INTAKE_DDL,
                *SESSION_WARMUP_SETS_DDL,
                *SESSION_CARDIO_DDL,
                *CHECKPOINT_REVIEWS_DDL,
                *EQUIPMENT_ACCESS_DDL,
            )
        ))
        if get_ledger_schema_version(conn) < CURRENT_LEDGER_SCHEMA_VERSION:
            set_ledger_schema_version(conn, CURRENT_LEDGER_SCHEMA_VERSION)
        conn.commit()

    def create_ledger_schema_on(self, conn) -> None:
        """Public form of :meth:`_create_ledger_schema_on` for off-store callers.

        The opt-in import materialises the current ledger schema on a migrated
        snapshot connection; it goes through this method rather than the private
        one so the store's schema rule stays owned here.
        """
        self._create_ledger_schema_on(conn)

    def ensure_account_schema(self) -> None:
        # Provisioned once at boot; guarded so the auth hot path never re-runs DDL.
        if getattr(self, "_account_schema_ready", False):
            return
        with self._catalog_lock:
            if getattr(self, "_account_schema_ready", False):
                return
            self._migrate_coach_alerts_shape()
            self.catalog_conn.executescript("""
                CREATE TABLE IF NOT EXISTS trainee_emails (
                    trainee_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token_hash TEXT PRIMARY KEY,
                    trainee_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reset_tokens_trainee ON password_reset_tokens(trainee_id);

                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    ledger_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    is_player INTEGER NOT NULL DEFAULT 1,
                    is_coach INTEGER NOT NULL DEFAULT 0,
                    session_epoch INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    deleted_at TEXT,
                    last_seen_at TEXT
                );
                -- Partial unique index: a username is unique among live accounts, so a
                -- deleted username can later be registered under a new immutable id.
                CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_active_username
                    ON accounts(username) WHERE deleted_at IS NULL;
                CREATE INDEX IF NOT EXISTS idx_accounts_ledger ON accounts(ledger_id);

                -- No account foreign key: deletion events outlive the account they target.
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_account_id TEXT,
                    source_ip TEXT,
                    reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_log_created
                    ON audit_log(created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_log_action_created
                    ON audit_log(action, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_log_target_created
                    ON audit_log(target_account_id, created_at DESC);
                CREATE TRIGGER IF NOT EXISTS audit_log_no_update
                    BEFORE UPDATE ON audit_log
                    BEGIN SELECT RAISE(ABORT, 'audit log entries are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS audit_log_no_recent_delete
                    BEFORE DELETE ON audit_log
                    WHEN julianday(OLD.created_at) >= julianday('now', '-365 days')
                    BEGIN SELECT RAISE(ABORT, 'audit log entries are retained for one year'); END;

                -- Server-owned Lifter/Coach plan state, keyed by the immutable account
                -- id and one row per capability. A missing row means the ongoing Free
                -- plan; eligibility is decided from the account's live capabilities,
                -- never from client-supplied role or username (issue #56).
                CREATE TABLE IF NOT EXISTS account_plans (
                    account_id TEXT NOT NULL,
                    capability TEXT NOT NULL CHECK (capability IN ('lifter', 'coach')),
                    plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'pro')),
                    status TEXT NOT NULL DEFAULT 'active',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, capability)
                );

                -- Owner-issued, account-bound coach invitations (ADR 013). Only the
                -- SHA-256 of the token is stored; the raw code is shown once to the
                -- operator. Redemption is a single atomic catalog transaction.
                CREATE TABLE IF NOT EXISTS coach_invites (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_coach_invites_account ON coach_invites(account_id);

                -- Coach-authored profile, keyed by the immutable account id and kept
                -- catalog-side so coach reads never open a player ledger (ADR-007).
                CREATE TABLE IF NOT EXISTS coach_profiles (
                    account_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    bio TEXT NOT NULL DEFAULT '',
                    specialization TEXT NOT NULL DEFAULT '',
                    capacity INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- Coach-issued player assignment invites (ADR 014, ticket #24). The code
                -- is a bearer code, not recipient bound: only the SHA-256 hash is stored,
                -- it is single-use, expiring, and bounded by roster capacity. Redemption
                -- claims the code and creates the assignment in one catalog transaction.
                CREATE TABLE IF NOT EXISTS assignment_invites (
                    token_hash TEXT PRIMARY KEY,
                    coach_account_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    redeemed_by_account_id TEXT,
                    assignment_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_assignment_invites_coach ON assignment_invites(coach_account_id);

                -- Mutually consented coaching assignment. Catalog-side so access checks
                -- and list views never open a player ledger. The partial unique index
                -- enforces at most one active assignment per player (context glossary).
                CREATE TABLE IF NOT EXISTS assignments (
                    assignment_id TEXT PRIMARY KEY,
                    coach_account_id TEXT NOT NULL,
                    player_account_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    ended_by TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_active_player
                    ON assignments(player_account_id) WHERE status = 'active';
                CREATE INDEX IF NOT EXISTS idx_assignments_coach ON assignments(coach_account_id);
                CREATE INDEX IF NOT EXISTS idx_assignments_player ON assignments(player_account_id);

                -- In-app notices for assignment events (redemption today; coach-facing).
                CREATE TABLE IF NOT EXISTS assignment_notices (
                    notice_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    assignment_id TEXT,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    read_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_assignment_notices_account ON assignment_notices(account_id);

                -- Player-requested program changes (ADR 018/027, ticket #28). Catalog-side,
                -- keyed by assignment. A request pins the exact program version/day/slot it
                -- targets and never mutates the program; resolution is an atomic claim that
                -- only flips a pending row, so double-apply and racing cancels fail cleanly.
                CREATE TABLE IF NOT EXISTS program_requests (
                    request_id TEXT PRIMARY KEY,
                    assignment_id TEXT NOT NULL,
                    coach_account_id TEXT NOT NULL,
                    player_account_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('exercise_substitution', 'split_change')),
                    program_version INTEGER NOT NULL,
                    day_name TEXT,
                    exercise_id TEXT,
                    replacement_exercise_id TEXT,
                    desired_weekly_frequency INTEGER,
                    desired_split_preference TEXT,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'applied', 'declined', 'cancelled')),
                    response TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_program_requests_assignment ON program_requests(assignment_id);
                CREATE INDEX IF NOT EXISTS idx_program_requests_player ON program_requests(player_account_id);

                -- Catalog-side per-assignment attendance summary, updated by evaluation so a
                -- roster read never opens the player's ledger (ADR 025/030). The cached
                -- ``timezone`` is the player's local timezone as of the last evaluation;
                -- absence falls back to UTC (ADR 031). ``last_workout_on`` mirrors the
                -- newest committed session date (NULL while the player has never trained)
                -- so the roster urgency order can rank it catalog-side (ticket #118).
                -- ``program_name`` mirrors the active program's display name (NULL while
                -- the player has no program) so the roster row can label it without
                -- mounting the ledger (ticket #120).
                CREATE TABLE IF NOT EXISTS roster_attendance (
                    assignment_id TEXT PRIMARY KEY,
                    current_missed_streak INTEGER NOT NULL DEFAULT 0,
                    last_evaluated_at TEXT,
                    timezone TEXT,
                    last_workout_on TEXT,
                    program_name TEXT
                );

                -- Coach-recorded check-ins (ADR 031, ticket #32). Catalog-side immutable
                -- facts: the coach records the date, contact channel, and an optional note.
                -- The row survives unassignment so the player keeps their history.
                CREATE TABLE IF NOT EXISTS check_ins (
                    check_in_id TEXT PRIMARY KEY,
                    assignment_id TEXT NOT NULL,
                    coach_account_id TEXT NOT NULL,
                    player_account_id TEXT NOT NULL,
                    checked_in_on TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_check_ins_assignment ON check_ins(assignment_id);
                CREATE INDEX IF NOT EXISTS idx_check_ins_player ON check_ins(player_account_id);

                -- Catalog-side episode state for the progression alerts (ADR 032,
                -- ticket #33). ``subject`` is '' for the systemic deload signal and
                -- the exercise id for performance regression, so a commit that does
                -- not include an exercise leaves its episode untouched.
                CREATE TABLE IF NOT EXISTS alert_signal_state (
                    assignment_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    episode_key TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (assignment_id, kind, subject)
                );

                -- Catalog-side marker of committed sessions whose progression
                -- signals have been evaluated (ADR 032, ticket #33). Written in the
                -- same transaction as the alert transitions, so re-processing an
                -- older session (even after later ones) is a no-op.
                CREATE TABLE IF NOT EXISTS progression_alert_sessions (
                    assignment_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY (assignment_id, session_id)
                );

                -- Catalog-side model usage metering (ADR 038, ticket #39). One row per
                -- model call, keyed by the immutable account id and model. ``account_id``
                -- is NULL only for an unattributed call (startup/eval), never a live
                -- request. ``estimated`` marks a row whose tokens fell back to the
                -- documented chars/4 heuristic because the provider returned no usage.
                CREATE TABLE IF NOT EXISTS model_usage (
                    id TEXT PRIMARY KEY,
                    account_id TEXT,
                    role TEXT NOT NULL,
                    model TEXT NOT NULL,
                    purpose TEXT,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_usage_account_created
                    ON model_usage(account_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_model_usage_created ON model_usage(created_at);

                -- Model-limit refusals are operational metadata, retained for 400 days.
                CREATE TABLE IF NOT EXISTS model_limit_hits (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('rate', 'daily_tokens')),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_limit_hits_account_created
                    ON model_limit_hits(account_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_model_limit_hits_created
                    ON model_limit_hits(created_at);

                -- Spend-alert state: one row per UTC calendar month. ``fired_at`` is the
                -- claim time and ``notified_at`` is set only after the owner email is
                -- delivered, so a failed/absent send leaves the row claimable for retry
                -- and a delivered one is never repeated (ADR 038, AC3).
                CREATE TABLE IF NOT EXISTS model_spend_alerts (
                    period TEXT PRIMARY KEY,
                    projected_usd REAL NOT NULL,
                    actual_usd REAL NOT NULL,
                    fired_at TEXT NOT NULL,
                    notified_at TEXT
                );

                -- Opt-in import audit (ADR 019, ticket #42). One row per imported
                -- source ledger, keyed to the new immutable account id. Only the
                -- snapshot fingerprint, the source file name, per-table counts,
                -- the operator's opt-in reference, and the import instant are
                -- stored: no training data and no contact details. The unique
                -- fingerprint makes re-running the import a refusal. The row is
                -- deleted with the account (ADR 015/039), so nothing identifying
                -- survives deletion; re-importing a deleted account's source is a
                -- genuinely new account, matching username reuse.
                CREATE TABLE IF NOT EXISTS account_imports (
                    import_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    counts_json TEXT NOT NULL,
                    opt_in_reference TEXT NOT NULL,
                    imported_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_account_imports_fingerprint
                    ON account_imports(source_fingerprint);
                CREATE INDEX IF NOT EXISTS idx_account_imports_account
                    ON account_imports(account_id);

                -- Owner-issued, account-bound single-use claim code for an imported
                -- account (ADR 019, ticket #42). Only the SHA-256 of the code is
                -- stored; the raw code is shown once by scripts/import_player.py.
                -- Redemption is atomic and sets the account's first password.
                -- Removed with the account, like its import audit row (ADR 045).
                CREATE TABLE IF NOT EXISTS account_claim_codes (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_account_claim_codes_account
                    ON account_claim_codes(account_id);

                -- Linked sign-in (CONTEXT.md): an external identity attached to
                -- exactly one account, keyed on (provider, subject) where the
                -- subject is the provider's immutable subject (Google's ``sub``).
                -- Never matched by email; no email, name or picture from the
                -- provider is stored. ``provider`` is data, so another provider
                -- needs no schema change (issue #113). An account holds at most
                -- one link per provider: UNIQUE(account_id, provider) (#114).
                CREATE TABLE IF NOT EXISTS linked_sign_ins (
                    provider TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    linked_at TEXT NOT NULL,
                    UNIQUE(provider, subject),
                    UNIQUE(account_id, provider)
                );
                CREATE INDEX IF NOT EXISTS idx_linked_sign_ins_account
                    ON linked_sign_ins(account_id);
            """)
            self._create_coach_alerts_schema()
            self._ensure_accounts_last_seen_at()
            self._ensure_roster_attendance_timezone()
            self._ensure_roster_attendance_last_workout_on()
            self._ensure_roster_attendance_program_name()
            self._ensure_model_spend_alert_columns()
            self._ensure_linked_sign_in_account_provider()
            self._ensure_coach_invites_revoked_at()
            self._commit_catalog()
            self._account_schema_ready = True

    _COACH_ALERTS_TABLE_SQL = (
        "alert_id TEXT PRIMARY KEY,"
        " assignment_id TEXT NOT NULL,"
        " coach_account_id TEXT NOT NULL,"
        " player_account_id TEXT NOT NULL,"
        " kind TEXT NOT NULL,"
        " dedupe_key TEXT NOT NULL,"
        " details TEXT NOT NULL,"
        " state TEXT NOT NULL DEFAULT 'new'"
        " CHECK (state IN ('new', 'acknowledged', 'resolved')),"
        " created_at TEXT NOT NULL,"
        " acknowledged_at TEXT,"
        " resolved_at TEXT,"
        " resolved_by TEXT"
    )

    _COACH_ALERTS_INDEX_SQL = (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_coach_alerts_dedupe"
        " ON coach_alerts(assignment_id, kind, dedupe_key)",
        "CREATE INDEX IF NOT EXISTS idx_coach_alerts_coach"
        " ON coach_alerts(coach_account_id, state)",
        "CREATE INDEX IF NOT EXISTS idx_coach_alerts_assignment ON coach_alerts(assignment_id)",
    )

    _LEGACY_COACH_ALERT_COLUMNS = (
        "alert_id, assignment_id, coach_account_id, player_account_id, kind,"
        " streak_start_date, last_missed_date, missed_count, state, created_at,"
        " acknowledged_at, resolved_at, resolved_by"
    )

    @classmethod
    def _coach_alerts_create_sql(cls, table: str) -> str:
        return f"CREATE TABLE IF NOT EXISTS {table} ({cls._COACH_ALERTS_TABLE_SQL})"

    def _create_coach_alerts_schema(self) -> None:
        """Fresh-create (or complete) the generalised ``coach_alerts`` and its indexes."""
        statements = [self._coach_alerts_create_sql("coach_alerts"), *self._COACH_ALERTS_INDEX_SQL]
        self.catalog_conn.executescript(";\n".join(statements) + ";")

    @staticmethod
    def _table_columns(cursor: Any, table: str) -> set[str]:
        """Column names present on ``table``; empty when the table does not exist."""
        cursor.execute(f"PRAGMA table_info({table})")
        return {str(row[1]) for row in cursor.fetchall()}

    def _copy_legacy_coach_alert_rows(self, cursor: Any) -> None:
        """Copy legacy missed-day rows into ``coach_alerts_new``, mapping to details.

        A separate method so a failure mid-rebuild is injectable in tests.
        """
        rows = cursor.execute(
            f"SELECT {self._LEGACY_COACH_ALERT_COLUMNS} FROM coach_alerts"
        ).fetchall()
        for row in rows:
            details = {
                "streak_start_date": str(row[5]),
                "last_missed_date": str(row[6]),
                "missed_count": int(row[7]),
            }
            cursor.execute(
                "INSERT INTO coach_alerts_new"
                " (alert_id, assignment_id, coach_account_id, player_account_id, kind,"
                " dedupe_key, details, state, created_at, acknowledged_at, resolved_at, resolved_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                    str(row[5]),
                    json.dumps(details),
                    str(row[8]),
                    str(row[9]),
                    row[10],
                    row[11],
                    row[12],
                ),
            )

    def _migrate_coach_alerts_shape(self) -> None:
        """Rebuild the legacy missed-day-shaped ``coach_alerts`` in place (ADR 031).

        Idempotent and crash-safe. The caller already holds ``_catalog_lock`` for
        the whole rebuild (``catalog_transaction`` is re-entrant). Shape detection
        handles every crash point:

        * old shape + no leftover: the normal rebuild;
        * old shape + leftover ``coach_alerts_new``: drop the orphan and rebuild;
        * no old table but leftover ``coach_alerts_new``: the crash happened after
          the old table was dropped, so the leftover is complete and is renamed;
        * already migrated: any orphan is dropped and nothing else happens.

        The rebuild runs inside one ``catalog_transaction`` ``BEGIN``/``COMMIT``
        and rolls back on any exception, so a failure leaves the old table and its
        rows intact.
        """
        cursor = self.catalog_conn.cursor()
        old_columns = self._table_columns(cursor, "coach_alerts")
        new_columns = self._table_columns(cursor, "coach_alerts_new")

        if old_columns and "dedupe_key" in old_columns:
            # Already migrated; clear any orphan left by an interrupted run.
            if new_columns:
                with self.catalog_transaction():
                    self.catalog_conn.execute("DROP TABLE IF EXISTS coach_alerts_new")
            return
        if not old_columns and not new_columns:
            return

        with self.catalog_transaction():
            cursor = self.catalog_conn.cursor()
            if not old_columns and new_columns:
                # The old table was already dropped before the crash: finish.
                cursor.execute("ALTER TABLE coach_alerts_new RENAME TO coach_alerts")
            else:
                cursor.execute("DROP TABLE IF EXISTS coach_alerts_new")
                cursor.execute(self._coach_alerts_create_sql("coach_alerts_new"))
                self._copy_legacy_coach_alert_rows(cursor)
                cursor.execute("DROP TABLE coach_alerts")
                cursor.execute("ALTER TABLE coach_alerts_new RENAME TO coach_alerts")
            for statement in self._COACH_ALERTS_INDEX_SQL:
                cursor.execute(statement)

    def _ensure_roster_attendance_timezone(self) -> None:
        """Additive ``timezone`` column on an existing ``roster_attendance`` (ADR 031)."""
        cursor = self.catalog_conn.cursor()
        columns = self._table_columns(cursor, "roster_attendance")
        if columns and "timezone" not in columns:
            cursor.execute("ALTER TABLE roster_attendance ADD COLUMN timezone TEXT")

    def _ensure_roster_attendance_last_workout_on(self) -> None:
        """Additive ``last_workout_on`` column on an existing ``roster_attendance`` (#118)."""
        cursor = self.catalog_conn.cursor()
        columns = self._table_columns(cursor, "roster_attendance")
        if columns and "last_workout_on" not in columns:
            cursor.execute("ALTER TABLE roster_attendance ADD COLUMN last_workout_on TEXT")

    def _ensure_roster_attendance_program_name(self) -> None:
        """Additive ``program_name`` column on an existing ``roster_attendance`` (#120)."""
        cursor = self.catalog_conn.cursor()
        columns = self._table_columns(cursor, "roster_attendance")
        if columns and "program_name" not in columns:
            cursor.execute("ALTER TABLE roster_attendance ADD COLUMN program_name TEXT")

    def _ensure_model_spend_alert_columns(self) -> None:
        """Additive ``fired_at``/``notified_at`` on an existing ``model_spend_alerts`` (ADR 038)."""
        cursor = self.catalog_conn.cursor()
        columns = self._table_columns(cursor, "model_spend_alerts")
        if columns and "fired_at" not in columns:
            cursor.execute("ALTER TABLE model_spend_alerts ADD COLUMN fired_at TEXT")
        if columns and "notified_at" not in columns:
            cursor.execute("ALTER TABLE model_spend_alerts ADD COLUMN notified_at TEXT")

    def _ensure_accounts_last_seen_at(self) -> None:
        """Add the day-granularity activity marker to existing account catalogs (#208)."""
        cursor = self.catalog_conn.cursor()
        columns = self._table_columns(cursor, "accounts")
        if columns and "last_seen_at" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN last_seen_at TEXT")

    def _ensure_coach_invites_revoked_at(self) -> None:
        """Add revocation state to existing coach invite catalogs (#210)."""
        cursor = self.catalog_conn.cursor()
        columns = self._table_columns(cursor, "coach_invites")
        if columns and "revoked_at" not in columns:
            cursor.execute("ALTER TABLE coach_invites ADD COLUMN revoked_at TEXT")

    def _ensure_linked_sign_in_account_provider(self) -> None:
        """``UNIQUE(account_id, provider)``: an account holds one link per provider (#114).

        Additive migration for catalogs created before the constraint existed
        (when only ``(provider, subject)`` was unique, two concurrent connects
        could leave an account with two identities for one provider). Such a
        duplicate keeps its earliest row and loses the rest, so the migration
        never fails on legacy data; a catalog that already enforces the rule —
        fresh ones through the table constraint — does no work here.
        """
        cursor = self.catalog_conn.cursor()
        indexes = cursor.execute("PRAGMA index_list(linked_sign_ins)").fetchall()
        for index in indexes:
            name, is_unique = str(index[1]), bool(index[2])
            if not is_unique:
                continue
            columns = [str(row[2]) for row in cursor.execute(f"PRAGMA index_info({name})").fetchall()]
            if len(columns) == 2 and set(columns) == {"account_id", "provider"}:
                return
        cursor.execute(
            "DELETE FROM linked_sign_ins WHERE rowid NOT IN ("
            " SELECT MIN(rowid) FROM linked_sign_ins GROUP BY account_id, provider)"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_linked_sign_in_account_provider"
            " ON linked_sign_ins(account_id, provider)"
        )
