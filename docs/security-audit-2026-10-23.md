# Security audit — 2026-10-23

Source-only security review of MYOS at commit `f2c418f` (plus the landing-page working tree of that day). Two reviewers worked independently and then cross-checked: Claude Opus 5.5 and Codex `gpt-6.1-sol` (read-only). Every finding below was confirmed in source by both reviewers, or confirmed by the second reviewer after the first raised it. Nothing was run against a deployed host (fly.dev, pages.dev, the VPS).

Tracking spec: #446.

## Result

No critical or high findings.

| # | Severity | Finding | Fix ticket | Status |
|---|---|---|---|---|
| 1 | medium | A fabricated `Authorization` header bypasses anonymous auth rate limits | #447 | fixed 2026-10-24 |
| 2 | medium | Outstanding reset tokens survive credential and recovery-email rotation | #448 | fixed 2026-10-24 |
| 3 | low | The exercise-history equipment lookup ignores coach-exercise ownership | #450 | fixed 2026-10-24 |
| 4 | medium (validated) | No decompressed-size budget on XLSX program imports | #449 | fixed 2026-10-24 |
| 5 | low | Program-draft warm-ups and substitutes disclose another coach's private exercise name | #458 | fixed 2026-10-24 |

Update the Status column as each ticket lands.

### Post-fix verification (2026-10-24)

Each fix was verified after implementation by Opus and `gpt-6.1-sol` (read-only), in up to four rounds, until both agreed the original boundary violation was closed and no regression remained. Every check ran as repository tests with dummy accounts; nothing was run against a deployed host. Verification changed or extended the fixes:

- **#447:** the per-account lockout initially let anyone extend a lock indefinitely, was not cleared by a password reset, was bypassed by the public account-deletion form, measured its window from the previous failure, and ran bcrypt inside the catalog-wide lock. All corrected: attempts during a cooldown neither count nor extend it, every successful credential rotation or sign-in clears it, the deletion form shares it, the window starts at the first failure and restarts after a cooldown, and bcrypt runs outside the catalog transaction. Every anonymous limiter route keys by client IP.
- **#448:** revocation (reset-link invalidation and session-epoch bump) now commits before the new password is written, so a failure leaves old links and sessions dead rather than alive. Password change, reset redemption, owner/CLI reset, password login and the deletion form serialize on a per-account credential lock kept beside the catalog database (shared by the CLI and every process using that catalog), and login re-checks the account id under that lock. Reset-link issuance re-checks the current verified recovery address inside the same serialization, so a link can no longer be mailed to an address replaced mid-request.
- **#449:** validation measured the risk (a 70 KB workbook reached 292 MB peak RSS; a 135 KB forged-size workbook reached 382 MB). The first fix counted bytes returned by `zipfile`, which an understated size with a prefix-matching CRC could defeat; the final fix decompresses each member's raw data with bounded output and requires stream EOF, the declared size and CRC, a supported method, unique names and at most 1,000 members (20 MiB per member and in total) before every `load_workbook` call. The forged workbook now peaks at 120 MB and is rejected.
- **#450:** equipment is shown only for library exercises, the requesting coach's own exercises, or exercises in the target ledger's program or workout history. Verification traced the other resolvers (workout logging, program requests, draft working exercises) and found them already guarded, and found finding 5.
- **#458 (finding 5, new):** a coach could reference another coach's private exercise id as a draft warm-up or suggested substitute and read its name back on publish and reload. Auxiliary ids now follow the same library / owner / prior-history rule, which a publication cannot satisfy for itself.

## 1. A fabricated `Authorization` header bypasses anonymous auth rate limits — medium

**Found by:** both reviewers, independently.

**Evidence.** `svc/rate_limit.py` `_key`:

```python
auth = request.headers.get("authorization", "")
if auth.lower().startswith("bearer ") and len(auth) > 20:
    return f"{ip}:{auth[-12:]}"
```

The header is never verified. Routes that take no bearer authentication still use this key:

- `POST /auth/login` (`LOGIN_LIMIT`, 5/min)
- `POST /auth/google`
- `POST /account/delete-request` (public HTML form, `PASSWORD_LIMIT`)
- `POST /auth/forgot-password` and the other `RESET_LIMIT` routes
- `POST /admin/login`

`service/auth.py` `login_player` has no per-account lockout.

**Principal / boundary / result.** An anonymous caller from one IP sends each request with a different last 12 characters in the header. Every request lands in a new bucket, so the per-IP login ceiling never applies. The result is unlimited online password guessing against any username, through both the API login and the public deletion form. The same trick floods reset emails. The admin login has its own lockout in `service/admin_auth.py`, so it is less exposed.

**Fix (#447).** Key anonymous routes on the IP bucket only. Key authenticated routes on the verified account id. Add a per-account failed-login cooldown that keeps the same generic 401.

## 2. Outstanding reset tokens survive rotation — medium

**Found by:** gpt-6.1-sol. Confirmed by Opus.

**Evidence.**

- `database/registry/recovery.py` `consume_reset_token` checks only that the token exists, is unused and has not expired.
- `invalidate_unused_reset_tokens` is called only from `service/password_reset.py` `owner_issue_reset_link`.
- `change_password` (`service/auth.py`), `reset_password_with_token` (`service/password_reset.py`) and the verified recovery-email swap never invalidate the other unused tokens.

**Principal / boundary / result.** Someone holding an unused reset link can still set a new password after the owner has changed theirs, completed a different reset, or moved the recovery email to a new mailbox. Examples: a person with brief access to the old mailbox, or a second link requested earlier. The attacker gets an account takeover for the remainder of the token TTL: `RESET_TOKEN_TTL_MINUTES`, default 30, or up to `ADMIN_RESET_LINK_TTL_MINUTES`, default 1440, for owner-issued links.

**Fix (#448).** Invalidate all unused tokens for the account in the same catalog transaction as every password replacement and every verified recovery-email swap.

## 3. Exercise-history equipment lookup ignores ownership — low

**Found by:** gpt-6.1-sol. Confirmed by Opus.

**Evidence.**

- `GET /dashboard/exercises/{exercise_id}/history` (`svc/routers/dashboard.py`) calls `service/dashboard.py` `exercise_equipment`.
- That calls `database/exercise_resolution.py` `resolve_exercise_display_row`, which calls `get_coach_exercise_unscoped` (`database/registry/coach_exercises.py`, `WHERE id = ?` only).
- `service/coach_history.py` performs the same lookup.

**Principal / boundary / result.** A signed-in player who knows another coach's private exercise id learns its `equipment` value. Workout history itself stays scoped to the caller's ledger. Exercise ids are UUIDs, so blind discovery is impractical.

**Fix (#450).** Resolve a coach exercise only for its owner, or when it appears in the target ledger's program or history.

## 4. XLSX program import: no decompressed-size budget — needs validation

**Found by:** both reviewers, independently.

**Evidence.**

- `POST /coach/assignments/{id}/program-import` reads at most `MAX_PROGRAM_IMPORT_FILE_BYTES` (1 MiB, compressed).
- `service/program_import.py` then calls `openpyxl.load_workbook(read_only=True)` in three places.
- The row and column guards run afterwards, and they read `max_row`/`max_column` from the uploader-controlled `<dimension>` tag.
- Shared strings and styles are parsed fully even in read-only mode.

**Principal / boundary / result (unproven).** A coach with an active assignment uploads a small, highly compressible workbook. The parse could exhaust memory on the single-worker API (512 MB Fly VM) and take the service down for every user.

**Missing fact.** The actual peak memory of `openpyxl` on such a file.

**Fix (#449).** Measure first. Then check the real decompressed bytes of each zip member, and the total, before every `load_workbook` call.

## Cleared (checked, no issue found)

- **JWT:** HS256 is pinned. The Google signup ticket carries `type`/`aud`, which `token_claims` refuses as a session token. Session epoch and `jti` revocation are checked before any ledger mount.
- **Google ID tokens:** the audience is pinned to `GOOGLE_WEB_CLIENT_ID` and the issuer is re-checked. Verification fails closed when Google sign-in is unconfigured. Signup completion is bound to the original ID token by digest.
- **Coach → player access:** every `/coach/assignments/{assignment_id}/…` route resolves through `get_active_assignment_for_coach` (assignment id + coach account id + active). Program-request apply and decline re-scope the request to that assignment.
- **Admin surface:** the middleware returns 404 without a valid session cookie. The login form has a CSRF token, TOTP and lockout. Admin security headers are applied.
- **Client IP trust:** only the configured proxy header is trusted (`Fly-Client-IP` on Fly, `cf-connecting-ip` on the VPS). Forwarding headers are ignored otherwise.
- **Recovery:** reset tokens use `token_urlsafe(32)` and are stored hashed, single-use, with a short TTL. Email codes are six digits, keyed-hashed, allow at most five failed attempts, and have an hourly issue cap.
- **Injection:** no reachable SQL injection, path traversal (the media route checks containment after `resolve()`), SSRF, shell call or unsafe deserialization.
- **AI:** the player assistant's tools close over the caller's ledger and are read-only. Coach AI context is assignment-gated and excludes player chat.
- **Web:** CORS uses an explicit origin list from `UI_BASE_URL`. `innerHTML` in `web_landing/landing.js` receives only repository-authored copy. The legacy `/app/` redirects have fixed same-origin targets.
- **Mobile:** release builds enforce HTTPS, App Links are verified, and tokens are stored in secure storage.
- **Secrets:** no production secret was found in tracked files or in a targeted `git log -p -S` search.

## Not assessed

Live deployment state: Cloudflare and Fly proxy configuration, R2 bucket ACLs, the VPS firewall, and real VM memory limits. These need an owner-side check.
