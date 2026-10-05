# Closed-trial release gate

This runbook collects the automated and human evidence required before MAYOS
expands beyond the four-week closed trial. Keep participant details in the
owner-controlled trial records; use account ids and usernames in this report.

## Automated gate

Run this block from the repository root. The API scenario uses temporary real
SQLite databases and the scripted chat model; the owner report test checks its
read-only catalog evidence path.

```bash
python -m pytest -q tests/test_closed_trial_release_gate.py tests/test_trial_gate_report.py
python -m pytest -q   # full regression baseline
ruff check .
cd mobile
flutter pub get
flutter analyze
flutter test
```

The API scenario covers registration and coach capability, assignment consent
and access boundaries, program authority and requests, alerts and Check-ins,
offline reconciliation, historical program sync, performed-date correction,
revocation, deletion, and restore. The mobile tests include the player consent
flow and the coach roster, request, and alert journey.

## Owner evidence report

Run the catalog-only report from the service environment. It lists each
retained active or ended Assignment, its start, full seven-day periods,
coach-published program evidence, and Check-in count. It exits nonzero when
fewer than five coach/player pairs qualify.

```bash
python scripts/trial_gate_report.py
python scripts/trial_gate_report.py --catalog /data/catalog.db --json
python scripts/trial_gate_report.py --catalog /data/catalog.db --as-of 2026-10-05
```

The pair gate passes when at least five pairs each have four full weeks, a
coach-published program, and two or more Check-ins. The report uses the
catalog's `program_published` notices and `check_ins` rows and does not open
Training ledgers.

Run the report and save its JSON before any participant deletes their Account
or before the deletion drill. Account deletion removes assignment notices and
the Player's Check-ins; if the report was not saved, point `--catalog` at a
restored copy of a pre-deletion catalog snapshot.

## Deployment smoke checks

Use [Deployment §10.5 Verification](DEPLOYMENT.md#105-verification-run-these-before-calling-it-live)
for health/readiness, registration/login, HTTPS chat, and restart persistence.
Follow [Deployment §10.7 Daily backups and restore](DEPLOYMENT.md#107-daily-backups-and-restore-issue-41)
for the running backup job, deletion-record protection, restore scheduling, and
readiness verification. Check
[§10.9 Password reset](DEPLOYMENT.md#109-password-reset-app-link-and-hosted-fallback-issue-38-adr-037)
and [§10.11 Android release](DEPLOYMENT.md#1011-android-release-for-the-play-closed-trial-issue-43)
for release-specific smoke checks.

Consented import of local history is not part of this gate: ADR 056 retired the
import and claim-code flow.

## Deletion and restore drill

Run this drill in staging or with an account created only for the drill. A
restore rewinds the catalog to the chosen snapshot, so record the target
snapshot date before starting.

1. Create a disposable player account and record a small amount of test data.
   Keep its immutable account id, username, and access token in the drill notes.
2. Create and record a backup snapshot before deletion:

   ```bash
   python scripts/backup_now.py
   ls -la /data/backups/daily
   ```

3. Delete the disposable account through the product's account deletion flow.
   Verify its old token receives `401` with `{"error":"account_deleted"}`,
   its live Training ledger is absent, and the durable `deletions.db` record
   exists.
4. Restore the pre-deletion snapshot. On the volume-owning Fly Machine, schedule
   the boot-time restore and restart the Machine:

   ```bash
   python scripts/restore_backup.py --latest --on-next-boot
   fly machine restart <machine-id>
   ```

   For a local or staging restore with the API stopped, use
   `python scripts/restore_backup.py --latest` instead.
5. Verify readiness stays unavailable until the restore finishes, then check
   that the deletion replay reports at least one record, the old account stays
   deleted, the old token still fails closed, and no deleted Training ledger is
   live.
   Run a full replay as a belt-and-braces confirmation:

   ```bash
   python scripts/reapply_deletions.py
   ```

6. Register the former username again and confirm the new token subject is a
   different immutable account id with an empty Training ledger.
7. Record the snapshot date, deletion id, restore summary, replay count,
   readiness result, and username-reuse result below.

The deployment procedure and the separate durable deletion record are described
in [Deployment §9](DEPLOYMENT.md#9-backup-disaster-recovery--wal-checkpointing)
and [§10.7](DEPLOYMENT.md#107-daily-backups-and-restore-issue-41).

## Authorization and data-integrity review

Before expansion, review the API evidence and operational records together:

- Confirm assignment rows show the expected coach/player ids, active or ended
  status, and start/end timestamps. Confirm the player's consented Assignment
  was created only after the access preview and explicit redemption.
- Confirm an unrelated or former Coach receives the generic `403 No active
  assignment` on player history, sessions, Check-ins, program requests, and
  alerts. Confirm the assigned Coach can read the same history while the
  Assignment is active.
- Confirm coach revocation ends access on the next read, including after an
  offline Workout sync. Confirm the Player ends the Assignment with the same
  effect, and retains their Training ledger and coach-authored program
  provenance.
- Compare the player's session count, session-commit count, and set count before
  and after sync retries. Confirm a repeated client session id adds no second
  Workout and a status lookup finds the committed response.
- Check API logs around the trial for unexpected `401`, `403`, and `5xx` spikes,
  repeated restore failures, authorization-denial patterns, and backup errors.
  Investigate request paths and account ids without copying bearer tokens,
  invite tokens, assistant conversations, or recovery credentials into notes.
- Confirm daily backup logs report a catalog snapshot and every live-account
  Training ledger, `deletions.db` remains outside snapshots, and restore logs
  show deletion replay plus orphan handling where applicable.
- Confirm the durable deletion record, catalog `deleted_at` state, and absent
  live Training ledger agree for each deletion drill. A restored catalog row
  must never revive the old identity.
- Review owner Audit log entries for the expected operator and deletion/restore
  actions; investigate unexplained capability changes or invite issuance.

## Usefulness interviews

Interview each Coach and Player separately before deciding to expand. Ask the
same neutral questions and capture concrete examples rather than a single
satisfaction score.

- Which part of training or coaching became easier during the four weeks?
- Which screen, alert, or request took the most effort to understand?
- Did the Coach's access match what the Player expected from the consent
  disclosure? Was anything surprising after revocation or when the Player ended
  the Assignment?
- Did offline Workout capture and reconnect preserve the activity as expected?
  What did the Player do when sync was pending or needed reconciliation?
- Were missed-day alerts and follow-up Check-ins timely and useful? Which were
  noisy or missing?
- Did the Coach-published Training program and program requests support a useful
  coaching conversation? What changed in response to a request?
- What data or behavior made either participant uncomfortable or uncertain?
- What one change would make the next month more useful, and would each person
  choose to continue using MAYOS?

Do not expand until the owner has reviewed both the operational evidence and
interview notes and recorded a decision.

## Results

| Evidence | Result / link | Owner | Date | Pass / notes |
| --- | --- | --- | --- | --- |
| API closed-trial gate |  |  |  |  |
| Flutter coverage and gates |  |  |  |  |
| Deployment smoke checks |  |  |  |  |
| Qualifying pairs |  |  |  |  |
| Deletion drill |  |  |  |  |
| Restore and replay drill |  |  |  |  |
| Authorization review |  |  |  |  |
| Data-integrity review |  |  |  |  |
| Coach interviews |  |  |  |  |
| Player interviews |  |  |  |  |
| Expansion decision |  |  |  |  |

| Pair | Coach account id / username | Player account id / username | Four weeks | Program published | Check-ins | Interview recorded |
| --- | --- | --- | --- | --- | --- | --- |
| 1 |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |
| 6 |  |  |  |  |  |  |
| 7 |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |
| 9 |  |  |  |  |  |  |
| 10 |  |  |  |  |  |  |
