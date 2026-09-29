# Myos: Authentication, Session Security & Account Recovery

This document specifies the Myos identity layer: credential storage, JWT session tokens, the revoke-all session-epoch model, recovery email, and the self-service plus operator-driven password recovery flows.

---

## 1. Overview & Threat Model

Myos is a **local-first, single-replica** engine. The identity layer is designed around three realities:

* **No cloud identity provider.** Account identity is an immutable id in the shared catalog registry (`accounts`); each account maps to a per-user SQLite ledger (`db/users/<ledger_id>.db`). There is no external identity provider or directory; email delivery is an optional, self-hosted SMTP backend (Section 9).
* **No account enumeration.** Unknown users and wrong passwords are indistinguishable, and password-recovery requests answer identically whether or not an email is linked.
* **Authentication is separate from inference.** Password hashing and JWT verification do not require a model to be loaded.

The attack surface considered here: credential stuffing (mitigated by strict login rate limits), token replay after theft (mitigated by per-token revocation and the session-epoch model), reset-token interception/replay (mitigated by hashed, single-use, short-TTL tokens), and account enumeration (mitigated by constant-shape responses).

---

## 2. Credential Storage

Credentials are stored per-ledger, never globally:

| Property | Value |
| :--- | :--- |
| Table | `auth_credentials` (one row per ledger, `id = 1`) |
| Columns | `password_hash`, `token_version`, `updated_at` |
| Algorithm | **bcrypt** (`bcrypt.gensalt()` per hash) |
| Password policy | 8–128 characters (`service/auth.py::validate_password`) |
| Plaintext | Never stored, never logged |

Password changes update the ledger credential and advance the account's session epoch in the shared catalog. The catalog also holds immutable ids, status, capabilities, and recovery identity (Section 6).

---

## 3. Registration, Login & the Legacy Claim Flow

`POST /auth/register` creates an immutable account id in the catalog registry, creates the account's ledger, stores the bcrypt hash, and immediately issues a JWT. `POST /auth/login` proves possession of the password and issues a JWT whose subject is that immutable account id.

An imported account (ADR 019) or an enrolled account whose ledger has no `auth_credentials` row uses a one-time claim flow. Claiming requires the **single-use, expiring claim code** the owner issues with `scripts/import_player.py`; only the code's SHA-256 is stored, and the raw code is handed over out of band. There is deliberately no code-less password set by username alone, and a bare local ledger without an account registry entry cannot be claimed through the API (see ADR 015/019):

```mermaid
sequenceDiagram
    autonumber
    participant UI as Flutter app
    participant API as FastAPI /auth
    participant SVC as service/auth.py
    participant DB as User Ledger

    UI->>API: POST /auth/login {trainee_id, password}
    API->>SVC: login_player()
    SVC->>DB: open_ledger + get_password_hash()
    alt No stored hash (imported / password-less account)
        SVC-->>API: code = claim_required
        API-->>UI: 403 "This ledger predates passwords. Set one to continue."
        Note over UI: The owner hands the claim code over out of band.
        UI->>API: POST /auth/claim {trainee_id, claim_code, password}
        API->>SVC: claim_player()
        SVC->>DB: consume_claim_code(hash) + set_password_hash(bcrypt)
        SVC-->>UI: JWT issued
    else Hash present
        SVC->>SVC: bcrypt.checkpw(password, hash)
        alt Match
            SVC-->>UI: JWT (sub, jti, tv)
        else Mismatch or unknown user
            SVC-->>UI: 401 "Invalid credentials." (identical shape)
        end
    end
```

Claim is **single-use and account-bound**: redeeming the code marks it used, and once a hash exists further `/auth/claim` calls return `401 Invalid or expired claim code.` Unknown account, wrong/expired/reused code, and an already-claimed ledger all return that same generic 401, so `/auth/claim` itself does not distinguish them. Note that `/auth/login` still returns `403 claim_required` for a password-less ledger by design, so the fact that an account is waiting to be claimed is observable to a caller who already knows its username. A too-weak password is a plain `400`.

---

## 4. JWT Session Tokens

Tokens are stateless HS256 JWTs issued by `svc/auth.py`:

| Claim | Meaning |
| :--- | :--- |
| `sub` | **Immutable account id** (never the reusable username) |
| `jti` | Unique token id — the unit of individual revocation |
| `tv` | **Session epoch** from the catalog account registry (Section 5) |
| `iat` / `exp` | Issued-at and expiry; lifetime `JWT_EXPIRY_HOURS` (default **2h**) |

`JWT_SECRET` is mandatory: the service refuses to sign or verify if it is unset (no insecure fallback). Verification (`svc/dependencies.py::get_current_player`) enforces, in order:

1. Bearer token present and syntactically valid (`token_claims`: `sub`, `jti`, `tv ≥ 1`).
2. Catalog registry lookup by `sub`: the account must exist, be live (a non-NULL `deleted_at` wins over a stale `status='active'`), and have the player capability. Missing, deleted, or inactive accounts fail closed **before any ledger is mounted**, so a bad token can never create a ledger as a side effect.
3. `tv` equals the account's current registry session epoch.
4. The account's ledger exists, then is mounted to check its token revocation list — identity comes **only** from the verified token, never from request bodies.
5. `jti` not present in the ledger's `revoked_tokens` table.
6. **Worker bind recheck.** Each route calls `bind_request` on the worker thread that will touch SQLite, which re-runs the registry live/capability/epoch check for the same immutable account before mounting. This closes the gap between the request-scoped checks above and the actual ledger work, so a deletion or epoch bump landing in between still fails closed.

Any failure yields a generic `401 Invalid or expired token.` / `Token has been revoked.`

**Backwards compatibility:** legacy tokens whose `sub` is a username are rejected, because only immutable account ids resolve in the registry. Tokens issued before schema v3 carry no `tv` claim and read as version 1 — they remain valid for an enrolled account until the first password event bumps the registry epoch.

---

## 5. Session Invalidation: The Token-Version Epoch (ADR 006)

Per-`jti` revocation (the `revoked_tokens` ledger, written by `POST /auth/logout`) can only kill **known** tokens. A password change must kill **all** sessions — including any held by an attacker — which is inexpressible per-`jti` without a session table. Myos instead uses a single monotonic counter per **account in the catalog registry**, so revocation survives independently of the deletable ledger:

```mermaid
sequenceDiagram
    autonumber
    participant UI as Flutter app
    participant API as FastAPI
    participant SVC as service/auth.py
    participant DB as Catalog Registry

    UI->>API: POST /auth/change-password {current, new} (Bearer tv=1)
    API->>SVC: change_password()
    SVC->>DB: verify current_password (bcrypt, ledger)
    SVC->>DB: set_password_hash(bcrypt(new))
    SVC->>DB: bump_account_session_epoch() -> tv=2
    SVC-->>UI: 200 "All sessions revoked; log in again."
    Note over UI,DB: Every token stamped tv=1 now fails verification step 3 — all devices logged out
```

`bump_account_session_epoch()` is invoked by **every** password event:

| Event | Path |
| :--- | :--- |
| Authenticated change | `POST /auth/change-password` |
| Reset via emailed token | `POST /auth/reset-password` |
| Operator CLI reset | `scripts/reset_password.py` (mandatory registry epoch when enrolled; ledger `token_version` fallback for a bare local ledger) |

Change-password failures return **400, never 401** — so a wrong current password is not misread by clients as session expiry.

---

## 6. Recovery Email and Legacy Client Gate (ADR 007)

Recovery identity lives in the **shared catalog** (`db/catalog.db`), not in per-user ledgers, because the logged-out forgot-password flow cannot know which ledger to open:

| Table | Columns | Purpose |
| :--- | :--- | :--- |
| `trainee_emails` | `trainee_id` (PK, **immutable account id** for live rows), `email` (UNIQUE), `updated_at` | Email ↔ account mapping |
| `password_reset_tokens` | `token_hash` (PK), `trainee_id` (**immutable account id** for live rows), `expires_at`, `used_at`, `created_at` | Single-use reset tokens |

Both tables are provisioned idempotently at catalog boot (`ensure_account_schema()` outside any held lock).

Live recovery rows are keyed by the immutable account id; **legacy username-keyed rows are ignored by lookup**. A stale email mapping or unredeemed token therefore cannot target a new account that reuses a deleted account's username (Section 7).

The legacy Streamlit client gates its dashboard and onboarding on a saved recovery email. The API provides `GET /auth/email` and `POST /auth/email`; it does not enforce that client gate. The Flutter client is the product client under development (ADR 017).

```mermaid
flowchart LR
    Login["Login / Claim / Register"] --> Check{"GET /auth/email"}
    Check -- "email present" --> Dashboard["Dashboard / Onboarding"]
    Check -- "email missing" --> Gate["Email Gate (blocking)"]
    Gate -- "POST /auth/email" --> Dashboard
    Check -- "401 expired" --> Login
    Check -- "404 stale service" --> Ops["'Restart service' message"]
```

In the legacy client, the sidebar's "Password & Recovery" panel edits the linked email after the gate.

---

## 7. Forgot / Reset Password

Tokens are generated with `secrets.token_urlsafe(32)`; **only the SHA-256 hash is stored**. TTL is `RESET_TOKEN_TTL_MINUTES` (default **30**, clamped 5–120). Consumption is atomic (a conditional `UPDATE … WHERE used_at IS NULL` under the catalog lock), so a token can never be redeemed twice, even concurrently.

```mermaid
sequenceDiagram
    autonumber
    participant User as Trainee (logged out)
    participant API as FastAPI /auth
    participant DB as Catalog DB
    participant Mail as SMTP / console-dev

    User->>API: POST /auth/forgot-password {email}
    API->>DB: lookup trainee_emails -> account_id (live accounts only)
    Note over API: ALWAYS 202 + identical generic message (anti-enumeration)
    API->>DB: store SHA-256(token) keyed by account_id, expires_at, used_at=NULL
    API->>Mail: send reset link (or log it in console-dev mode)
    User->>API: POST /auth/reset-password {token, new_password}
    API->>API: validate password policy BEFORE consuming
    API->>DB: atomic consume (unused AND unexpired)
    API->>DB: set_password_hash + bump_account_session_epoch + prune tokens
    API-->>User: 200 "Please log in with the new password."
```

Defensive details:

* Weak new passwords are rejected **before** token consumption — a failed attempt does not burn the link.
* Unknown, expired, reused, and fabricated tokens all share one generic `400 Invalid or expired reset code.`
* Expired and consumed tokens are pruned on each request.
* The reset link is `RESET_LINK_BASE_URL/reset-password?token=…`. There is no `UI_BASE_URL` fallback: the retired Streamlit UI does not serve `/reset-password`, so an unset `RESET_LINK_BASE_URL` defaults to the API's own local base (`http://localhost:8000`) for development only. The path is an **Android App Link** when the app is installed and a **hosted fallback page** otherwise. In production the host must be identical in all three places: `RESET_LINK_BASE_URL`, the Android App Link intent-filter host (`-PappLinkHost`), and where `/.well-known/assetlinks.json` is served.
  * `GET /reset-password` on the API serves a self-contained HTML page (strict nonce CSP, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`) that reads the token from `location`, immediately scrubs it from the URL with `history.replaceState(null, '', location.pathname)`, and POSTs to `/auth/reset-password`; the token is never reflected into the HTML. A non-string error body (for example a 422 validation list) falls back to the generic message.
  * `GET /.well-known/assetlinks.json` serves the Digital Asset Links statement (`ANDROID_APP_PACKAGE`, `ANDROID_APP_SHA256_CERT_FINGERPRINTS`). Each fingerprint may use upper/lower case and colons or not; it is normalised to the uppercase colon-separated 32-byte form, invalid entries are skipped with a logged warning, and no valid fingerprint returns 404 rather than an invalid file.
  * The API installs an `uvicorn.access` log filter (`svc/app.py::RedactResetTokenFilter`) that rewrites any `token=…` query value to `token=[REDACTED]`, so the single-use token never lands in access logs regardless of the uvicorn CLI flags.
* The legacy `UI_BASE_URL/?reset_token=…` link for the retired Streamlit Recover Access tab is no longer emitted (ADR 037).

---

## 8. Operator Admin Reset (No-Email Backstop)

When no recovery email exists (or its delivery fails), the operator resets the password directly against the ledger:

```bash
# Interactive (password never touches shell history)
python scripts/reset_password.py <trainee_id>

# Non-interactive (exposed in process list/history — use only for automation)
python scripts/reset_password.py <trainee_id> --password 'new-secret'

# Custom storage locations
python scripts/reset_password.py <trainee_id> \
  --catalog db/catalog.db --users-dir db/users --backups-dir db/backups
```

The CLI validates the password policy, writes a fresh bcrypt hash, and bumps the ledger `token_version`. When the ledger is **enrolled** in the registry it then mandatorily advances the account's registry session epoch — failing loudly rather than reporting success if that cannot be done — so every registry-verified API session is revoked, and it reports the real registry epoch. A bare local ledger with no registry account keeps the legacy behavior and reports its ledger `token_version`. It prunes the revocation ledger and never prints or logs the hash.

---

## 9. Email Delivery

`service/email_sender.py` is deliberately optional at the transport level:

| Configuration | Behavior |
| :--- | :--- |
| `SMTP_HOST` **unset** | **Console-dev backend**: the reset link is written to the service log — safe for local dev, never for shared hosting |
| `SMTP_HOST` set | STARTTLS (default) or implicit TLS (`SMTP_USE_TLS=false`), optional `SMTP_USER`/`SMTP_PASSWORD` auth, 10s timeout |

Delivery failures are logged and swallowed; the client response stays generic. The admin CLI is the guaranteed fallback.

---

## 10. Endpoint & Rate-Limit Reference

| Endpoint | Auth | Limits | Notes |
| :--- | :--- | :--- | :--- |
| `POST /auth/register` | — | 5/min | 409 if ID taken; 201 + JWT |
| `POST /auth/login` | — | 5/min | 401 generic; 403 claim required |
| `POST /auth/claim` | — | 5/min | Requires owner-issued single-use claim code; 401 generic |
| `POST /auth/logout` | Bearer | — | Revokes presenting `jti`; 204 |
| `POST /auth/change-password` | Bearer | 10/min | Revokes **all** sessions; 400 on failure |
| `DELETE /auth/account` | Bearer | 10/min | Password-confirmed durable deletion (ADR 039); 400 generic on wrong password |
| `GET /auth/email` | Bearer | — | `{"email": str \| null}` |
| `POST /auth/email` | Bearer | 10/min | Normalizes; 400 on invalid/conflict |
| `POST /auth/forgot-password` | — | 3/hour | Always 202 with generic message |
| `POST /auth/reset-password` | — | 3/hour | Single-use token; bumps epoch |
| `GET /reset-password` | — | — | Hosted fallback reset page (no-store, no-referrer, strict CSP) |
| `GET /.well-known/assetlinks.json` | — | — | Android App Link statement; 404 when no fingerprint configured |

Rate-limit keys combine the client IP with a bearer-token suffix when present, so authenticated clients do not share a bucket. All limits are overridable via `RATE_LIMIT_*` environment variables.

### Environment Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `JWT_SECRET` | **required** | HS256 signing/verification key; service refuses to start signing without it |
| `JWT_EXPIRY_HOURS` | `2` | Access-token lifetime |
| `UI_BASE_URL` | `http://localhost:8501` | CORS origin(s), comma-separated (not used for reset links) |
| `RESET_LINK_BASE_URL` | `http://localhost:8000` | Reset-link / App Link base (`<base>/reset-password?token=…`) |
| `ANDROID_APP_PACKAGE` | `com.mayos.mayos_mobile` | Package name in `assetlinks.json` |
| `ANDROID_APP_SHA256_CERT_FINGERPRINTS` | unset (⇒ 404) | Comma-separated signing-cert SHA-256 fingerprints (case/colons optional; normalised) |
| `RESET_TOKEN_TTL_MINUTES` | `30` | Clamped to 5–120 |
| `SMTP_HOST` | unset | Unset ⇒ console-dev backend |
| `SMTP_PORT` / `SMTP_USE_TLS` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | `587` / `true` / — / — / `no-reply@myos.local` | SMTP transport |
| `RATE_LIMIT_LOGIN` / `_REGISTER` / `_PASSWORD` / `_RESET` | `5/min` / `5/min` / `10/min` / `3/hour` | Overrides |
| `MAYOS_DELETIONS_DB` | `<catalog dir>/deletions.db` | Durable deletion-record store, kept **outside** catalog snapshots (ADR 039) |

---

## 11. Known Limitations

* **No email ownership verification.** The gate links whatever address the authenticated trainee supplies; a bogus address simply loses self-service recovery (the admin CLI remains the backstop). There is no double opt-in loop.
* **Single-replica rate limiting.** `slowapi` state is in-process; horizontally scaling the service would require a shared store.
* **Console-dev fallback is unsafe on shared hosts.** Leaving `SMTP_HOST` unset logs reset links to `logs/myos.log`; always configure SMTP outside local development.
* **JWT secret rotation** invalidates all sessions globally (all ledgers verify against one `JWT_SECRET`); per-ledger rotation is out of scope.

---

## 12. Durable Account Deletion (ADR 015/039)

An account holder deletes their account with `DELETE /auth/account` carrying `{"password": "..."}` (rate-limited with the password limit). A wrong password returns a generic `400 Invalid credentials.` and changes nothing. On success every session is dead and the account's active data is gone. The full decision and per-table breakdown are ADR 039; the operator-facing recovery details are in [`DEPLOYMENT.md`](DEPLOYMENT.md).

```mermaid
sequenceDiagram
    autonumber
    participant App as Flutter app
    participant API as FastAPI /auth
    participant DB as Catalog
    participant DEL as deletions.db
    participant FS as Users / backups

    App->>API: DELETE /auth/account {password} (Bearer)
    API->>DB: verify password (bcrypt, ledger)
    API->>DEL: (a) write durable deletion record FIRST
    API->>DB: (b) one transaction: status='deleted', deleted_at, session_epoch+1, clear recovery/invites/coach profile, end assignments, delete relationships
    API->>FS: (c) close conn, remove ledger (.db/-wal/-shm) + backups/<ledger>/
    API-->>App: 200 "Account deleted. All sessions have been ended."
    Note over DEL,DB: Any later startup/restore replays the record, so an old token or a restored catalog snapshot cannot resurrect the identity
```

Key properties:

* **Revoke-all + fail closed.** The catalog transaction bumps `session_epoch`, so every bearer and remember-me token fails verification (Section 4/5). The partially-deleted account also fails closed because `deleted_at` is authoritative (a non-NULL `deleted_at` wins over a stale `status='active'`).
* **Crash-safe and resumable, never rolled back.** The durable record is written before any catalog change and carries an `applied_at` marker. Service startup and the hourly sweep run an incremental replay that completes only not-yet-applied records (so an interrupted deletion resolves without a restart); the restore path runs the full replay (`scripts/reapply_deletions.py`) which re-checks every record. `deletions.db` is kept **outside** the catalog/ledger backup archive, backed up separately and append-only, and is never restored over a newer copy — so a restore cannot undo a deletion. A replayed record never removes a ledger that a reused username's **new** account owns.
* **Username reuse only as a new account.** The partial unique username index (`WHERE deleted_at IS NULL`) frees the name; registering it again creates a new immutable `account_id` with an empty ledger, and the old `sub` still resolves to the deleted id, never the new account. A reused username also gets a **distinct `ledger_id`/ledger path** (`<username>-<account_id[:12]>`), so replaying the old deletion record can never remove the new account's ledger.
* **Deletion signal for other devices.** An authenticated request whose token signature verifies but whose subject is deleted returns `401 {"error": "account_deleted"}` (distinct from the ordinary `{"detail": ...}` 401 for expiry/revocation). The Flutter client uses it to erase that account's protected local data — drafts, cached program/prescriptions, cached chat history, and disclosure acceptance — without the logout keep/discard prompt, then clears the session. An ordinary 401 keeps the normal logout behavior.

### Information disclosure

`account_deleted` is disclosed only to a caller holding a **validly signed token** for that account: the JWT signature and required claims are verified before the registry records are consulted, so an attacker who has not obtained the token learns nothing, and an unknown account still returns the generic `401 Invalid or expired token.`

---

*Related: ADR 006 (token-version session epoch), ADR 007 (catalog-side recovery identity), and ADR 015/039 (durable account deletion) in [`DECISIONS.md`](../DECISIONS.md); deployment configuration in [`DEPLOYMENT.md`](DEPLOYMENT.md).*
