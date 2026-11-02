# #377 rehearsal: problems found and how they were solved

A record of every problem hit while moving the API from Fly.io to the Contabo server
(spec #571), with how it was found, the real cause, the fix and the evidence that it
is fixed. The rehearsal facts and first measurements are in
[rehearsal-2026-10-31.md](rehearsal-2026-10-31.md). Production stayed on Fly
throughout; `api.mayos.online` answered 200 at every check.

## Summary

| # | Problem | Cause | Fix | Status |
| ---: | :--- | :--- | :--- | :--- |
| 1 | Server bootstrap stopped half-way | SIGPIPE under `pipefail` | #575 `d3676a07` | ✅ verified on the server |
| 2 | Scripts failed from a Windows checkout | CRLF line endings, no executable bit | #575 `d3676a07` | ✅ verified |
| 3 | Bootstrap expected an `ubuntu` user | Contabo logs in as `root` (and cloud-init already made `ubuntu`) | Checklist, #572/#575 | ✅ |
| 4 | First deploy crashed after readiness | Empty argument lost over `ssh` | #577 `8a160147` | ✅ verified by redeploy |
| 5 | First deploy started only the API | `--no-deps api` assumed the companions already ran | #577 `8a160147` | ✅ verified |
| 6 | Staging returned 502 | Tunnel route saved as `https://api:8000` | Route set to `http://api:8000` | ✅ `/readyz` 200 |
| 7 | No load-test script in the repo | The 2026-10-07 script was never committed | #576 `9a0b1300` | ✅ |
| 8 | Load tests above 20 Players measured nothing | Every Player's setup started at once | #579 `07a602f8` | ✅ 200/200 ready |
| 9 | Staging ran on an empty database | The local data archive was deleted, and the restore didn't check it | Hash-guarded restores | ✅ |
| 10 | 0.8 CPU-seconds per request | The `exercises` view materialized the whole catalog on every join | #578 `b873835f` | ✅ about 100× per query, 2.6× throughput |
| 11 | Ceiling of 11–12 req/s with half the CPU idle | Full program rebuild on every request, single GIL | #582 ✅ (+17% req/s, 3× faster save at 20 Players), then #583 / ADR 096 | 🔄 step 2 next |
| 12 | Litestream CPU grows with the number of ledgers | A directory watch over every ledger | Tuning item in #377 | ⏳ open |
| 13 | The test suite can't run from a fresh clone | Git-ignored `db/catalog.db`, file-handle leak, no `git` in the image | #580 | ⏳ open |
| 14 | Two tests already failing on master | A clock-dependent test; `.conn` use in `service/injuries.py` | #581, merged in `3ea1a0b7` | ✅ |
| 15 | Long jobs ran without time limits or start checks | Orchestration mistakes | Process change | ✅ |
| 16 | The server hard-rebooted 6 times on 2026-11-01, then froze for about 80 minutes that evening and for about 6.5 hours overnight | Contabo host (patching per support; the freeze left no trace in the guest) | Stack restarts by itself; UptimeRobot and Sentry in place; go/no-go rule in #602 | ⏳ watching |

## Server setup

### 1. The bootstrap aborted half-way (exit 141)

- **Symptom.** `setup_vps.sh` stopped right after installing packages: Docker's apt source was added, but there was no firewall, no `deploy` user and no `/opt/mayos`.
- **How found.** The exit status 141 is 128 + SIGPIPE. Reading `server_bootstrap.sh`, the next step was `ssh_port="$(sshd -T | awk '$1 == "port" { print $2; exit }')"`.
- **Cause.** `awk` exits at the first match while `sshd -T` is still writing, so `sshd` receives SIGPIPE. Under `set -o pipefail` the pipeline returns 141, and `set -e` stops the script. The script had never run against a real server before.
- **Fix (#575).** Readers no longer exit early: `awk '... && !found { print; found = 1 }'` consumes all input. The same pattern was fixed in the owner-key decode and in two `docker ps | head -n 1` pipelines in `deploy_server.sh`.
- **Verified.** In a simulation, the old form returns 141 and the new form returns 0. The real bootstrap then completed: deploy SSH works, `root` and `ubuntu` SSH and password logins are refused, and only port 22 is open from outside.

### 2. Scripts failed from a Windows checkout

- **Symptom.** `/usr/bin/env: 'bash\r': No such file or directory`, then `Permission denied` for `./deploy/setup_vps.sh`.
- **How found.** `grep -c $'\r'` from WSL showed 172 and 423 CRs in the two scripts the previous commit had touched (Git Bash on Windows hid them), and `git ls-files -s` showed mode `100644`.
- **Cause.** `core.autocrlf=true` with no `.gitattributes`, so git rewrote changed files with CRLF on checkout. The scripts were never committed as executable.
- **Fix (#575).** A `.gitattributes` forces LF for `*.sh`, `Dockerfile*`, YAML, TOML and config files, and `deploy/*.sh` are now `100755`. Deploys run from a checkout on WSL's own filesystem with `core.autocrlf false` (`docs/SERVER_SETUP.md`).
- **Verified.** `tests/test_deploy_script_attributes.py` asserts the mode and `eol=lf` for every deploy script, and `./deploy/setup_vps.sh` ran as documented.

### 3. The bootstrap user

- **Symptom.** Contabo's image logs in as `root`, while `setup_vps.sh` expects a non-root `ubuntu` user.
- **Finding.** cloud-init had already created `ubuntu` with passwordless sudo and an empty `authorized_keys`.
- **Fix.** The checklist (#572, refined in #575) says to check `id ubuntu`. If the user exists, only install the owner's key; otherwise create it.
- **Verified.** The `ubuntu` key login and `sudo -n` succeeded, and setup's hardening then removed that key.

## Deploy

### 4. The first deploy crashed after readiness (`$3: unbound variable`)

- **Symptom.** The API was ready, then the history step failed and no rollback target was recorded.
- **How found.** `remote_bash` passed `"$commit" "$tag" "$previous_tag"` through `ssh`. On a first deploy `previous_tag` is empty.
- **Cause.** `ssh` joins its arguments into one command string, so an empty argument disappears. The remote side saw two arguments, and `set -u` stopped at `$3`.
- **Fix (#577).** Each argument is shell-quoted with `printf %q` before it goes into the remote command. The script's dispatch moved into `main`, so tests can source it without a test hook.
- **Verified.** A stub-`ssh` test shows an empty argument and one containing a space arrive intact. The real redeploy recorded history with two kept tags.

### 5. The first deploy started only the API

- **Symptom.** `cloudflared` and Litestream weren't running after the first deploy.
- **Cause.** The deploy ran `compose up --no-deps api` on the assumption that the companion services already ran.
- **Fix (#577).** After a successful readiness check, the deploy runs `compose up -d --no-build cloudflared litestream`, which is a no-op when they already run unchanged.
- **Verified.** On the redeploy both were reported as `Running` (not restarted). Behaviour tests show they start after readiness and never on the failed-readiness path.

### 6. Staging returned 502

- **Symptom.** `https://staging.mayos.online/readyz` returned 502.
- **How found.** `cloudflared` logged `tls: first record does not look like a TLS handshake ... originService=https://api:8000`.
- **Cause.** The Tunnel route was saved with `https://`; the API speaks plain HTTP inside the Compose network.
- **Fix.** Route edited in Cloudflare to `http://api:8000`.
- **Verified.** `/readyz` returned 200 through the Tunnel, while `api.mayos.online` stayed on Fly.

## Load testing

### 7. No load-test script

- **Cause.** The 2026-10-07 Fly measurement was referenced in ADR 072 but the script was never committed.
- **Fix (#576).** `scripts/load_test.py` drives the real public API (register or log in, onboarding intake, program reads, workout saves, optional chat) and reports requests/s and median and p95 latency per request type. It refuses the production hosts without `--allow-production`.

### 8. Tests above 20 Players measured nothing

- **Symptom.** At 50 or more Players no simulated Player became ready: `network_error`, and `context canceled` in the `cloudflared` logs.
- **Cause.** Every Player's registration and program generation started in the same instant, beyond the client's 30 s timeout. The registration and login limits (5 a minute per IP) also blocked a single-machine test.
- **Fix (#579).** A setup cap (`--setup-concurrency`), a staggered start (`--ramp-up`, with ramp traffic excluded from the stats), a configurable request timeout, and `--reuse-accounts`. The login limits are raised on staging only for a run and restored afterwards.
- **Verified.** 200 of 200 Players became ready.

### 9. Staging ran on an empty database during one run

- **Symptom.** Every Player failed setup with 502 in one run.
- **Cause.** The local archive folder had been deleted, and the restore step deleted `/data` and then found nothing to unpack. My script ran the delete without checking the archive first.
- **Fix.** A fresh, verified copy from Fly. Every restore now refuses to touch `/data` unless the archive exists with the exact sha256, both locally and on the server.
- **Verified.** Every later restore reported 15 ledgers. Production was never affected.

## Performance

### 10. 0.8 CPU-seconds per request (#578)

- **Symptom.** At 20 Players: 4.6 req/s, 3.1 s median save, with the API using 3.5–4.4 of the 4 cores.
- **Ruled out by measurement.**
  - The hardware: Contabo's core is only 20–25% slower than Fly's.
  - Litestream: turning it off didn't change throughput.
  - Native thread oversubscription: `OMP_NUM_THREADS=1` didn't change it.
  - The embedding model: the save and read paths don't call it, so going back to PyTorch from ONNX would not help.
- **How found.** `py-spy` on the API under load put 41% of CPU in `_load_program` and 33% in `_current_exercise_names`, both on queries joining the `exercises` view. `EXPLAIN QUERY PLAN` showed `MATERIALIZE exercises` / `SCAN e` / `AUTOMATIC COVERING INDEX`.
- **Cause.** The per-ledger `exercises` view joined `exercise_display_names` with a LEFT JOIN. SQLite can't flatten such a view when it sits on the right side of another LEFT JOIN, so every program query copied all 1,328 catalog exercises and built a throw-away index: 4.3 ms per query against 0.04 ms on the base table.
- **Fix (#578).** The display name became a correlated subquery, so the view has no join, SQLite flattens it, and lookups use the primary-key index. Columns and values are unchanged.
- **Verified.**
  - A query-plan test asserts no `MATERIALIZE` or `SCAN` and a primary-key search.
  - A display-name test covers the curated name and the catalog fallback.
  - On the server, the suspect test files gave identical results on master and #578.
  - At 20 Players: 4.6 → 12.0 req/s, save 3.1 s → 0.68 s, program read 2.2 s → 0.32 s.

### 11. A ceiling of about 11–12 req/s with half the CPU idle

- **Symptom.** After #578, the stepped test (20 → 200 Players) showed flat throughput, linear latency growth and no errors:

| Players | Req/s | Save median / p95 | Read median | Errors | CPU idle |
| ---: | ---: | :--- | ---: | ---: | ---: |
| 20 | 12.0 | 0.68 / 1.42 s | 0.32 s | 0 | 56% |
| 50 | 11.2 | 3.42 / 4.12 s | 2.50 s | 0 | 49% |
| 100 | 10.8 | 7.86 / 8.56 s | 6.82 s | 0 | 46% |
| 200 | 10.6 | 15.7 / 16.8 s | 14.9 s | 0 | 42% |

- **How found.** A wall-clock and a GIL-only `py-spy` profile at 50 Players. The API runs one Uvicorn worker (ADR 072, single SQLite writer), and its active threads sat in `get_active_program`. The GIL holder was spread over JSON decoding (~10%), `_current_exercise_names` (~18%, including one query per exercise id), `_load_program` (~14%) and Pydantic build and copy (~9%).
- **Cause.** Every request, saves included, rebuilt the full active program in Python, sometimes more than once. One process means one GIL, so those rebuilds ran one at a time.
- **Fix, step 1 (#582, merged in `99212646`).** The per-id name lookups became one set-based query, and the active program is loaded once per request and passed down.
  - Review found two gaps in the first version: a workout save still loaded the program twice (the second load was in training status), and the first fix for that broke the older direct-commit path (`None` meant "not loaded" in one module and "no program" in the other). Both were corrected, with tests.
  - Verification on the server: 16 affected test files pass on master + #581 + #582. Master fails one of them (the roster snapshot test fixed by #581).
  - Same stepped test, same verified data copy, image `99212646c54c`:

| Players | Req/s (before → after) | Save median / p95 after | Save median before | Read median after | Errors | CPU idle |
| ---: | :--- | :--- | ---: | ---: | ---: | ---: |
| 20 | 12.0 → **14.1** | **0.23** / 1.48 s | 0.68 s | 0.18 s | 0 | 59% |
| 50 | 11.2 → **13.7** | **2.51** / 3.92 s | 3.42 s | 1.88 s | 0 | 48% |
| 100 | 10.8 → **12.6** | **6.35** / 8.73 s | 7.86 s | 5.76 s | 0 | 45% |
| 200 | 10.6 → 9.8 | 17.1 / 22.0 s | 15.7 s | 15.9 s | 0 | 42% |

  - **Result.** About 17% more throughput up to 100 Players, and a workout save at 20 Players is three times faster (0.23 s median). The ceiling is still about 13–14 req/s with 40–60% of the CPU idle, so the single-GIL rebuild still dominates. At 200 Players throughput fell: by then 215 ledgers exist, and Litestream used 56–77% CPU (problem 12). Step 2 is needed for more capacity.
- **Fix, step 2 (#583, ADR 096).** Cache the active program per Player. SQLite triggers maintain a per-ledger and per-catalog revision (a random generation plus a counter), so any write from any code path invalidates the cache. The tables are additive, so there is no schema version bump and rollback stays available. #582's numbers are in, so this is next.

### 12. Litestream CPU grows with the number of ledgers

| Ledgers | Litestream CPU |
| ---: | :--- |
| 15 | 2.5% idle |
| 140–215 | 46–100% after load |
| about 750 | 65% idle, 110% under load |

- **Cause.** Litestream 0.5 watches the ledger directory and monitors every database separately.
- **Status.** Open in #377 ("sync interval adjusted if needed"). It needs tuning before Player numbers grow.

## Test environment

### 13. The suite can't run green from a fresh clone (#580)

- **Symptoms.**
  - Without `db/catalog.db`: about 2,000 errors.
  - `Too many open files` at the default limit of 1,024.
  - `git`-based tests error where `git` is missing.
  - `test_player_chat_privacy.py` takes about 9.6 minutes, which looked like a hang.
- **Causes.**
  - Tests copy a git-ignored development catalog.
  - The run leaks file handles.
  - Two tests shell out to `git`.
- **Workaround used.** Copy the catalog in, raise the file limit and run files separately with time limits, in 3 parallel shards on the server.
- **Status.** Open as #580.

### 14. Two tests already failing on master (#581)

- **`test_roster_snapshot`.** The test seeded adherence through 2026-10-25, but the snapshot read the real date, so its 7-day window drifted forward. The fix pins the service clock in the test.
- **`test_store_isolation[service]`.** `service/injuries.py` used `ledger.conn` directly, breaking ADR 041. Two ledger methods now do those reads and writes.
- **Verified.** On the server: roster 20/20, store isolation 27/27, injuries 41/41 and structured intake 55/55 (previously 19/20 and 26/27).

## Process

### 15. Orchestration mistakes and what changed

- **What went wrong.**
  - A suite run hung for about 1.5 hours without an overall time limit.
  - A parallel run silently never started, and I didn't check.
  - An old run's cleanup deleted a newer run's working copy.
- **What changed.**
  - Every step has a time limit.
  - Each run's start is confirmed (containers listed, files counted).
  - Cleanups only touch their own run's folder.
  - Restores are hash-guarded.
  - Long tests run on the server, not on the owner's PC.
  - A comparison run tested one file instead of 16: `ssh host bash -s -- "$FILES"` re-splits
    the argument, so the remote script got only the first name. The list now travels as an
    environment variable, and the script prints the file count before it runs anything.

## Hosting

### 16. The server rebooted itself six times in one day

- **Symptom.** A test run stopped mid-way with `server not responding`. `uptime` showed a
  fresh boot, and `last -x` listed six boots on 2026-11-01 (03:50, 07:20, 08:49, 09:22,
  11:52, 13:46 CET), none with a clean shutdown.
- **How it was found.** The previous boot's journal ends abruptly, with no shutdown, kernel
  panic or out-of-memory messages. At least four reboots happened while nothing of ours was
  running on the server.
- **Cause.** Contabo support: host patching for an active VPS/VDS security advisory can
  restart VPSs without individual notice. They could not confirm that our reboots were
  caused by it. Progress is posted on Contabo's status page.
- **What already holds.** After every reboot, Docker brought `api`, `cloudflared` and
  `litestream` back by themselves (`restart: unless-stopped`), and staging answered
  `/readyz` 200 afterwards. Litestream keeps replicating to R2.
- **What remains before move day (#378).**
  - UptimeRobot on `/readyz`, so an unexpected restart alerts the owner.
  - The daily backup is switched back on (it is off only for the rehearsal).
  - The restore drill from the R2 replicas proves the backups restore.
  - Test runs record `uptime -s` before and after, so a reboot can't pass for a test
    failure.
  - If reboots continue after the advisory closes, ask Contabo to move the VPS to another
    host node.
- **Second incident: a silent freeze (same day, evening).**
  - UptimeRobot (set up that evening: email and Discord) alerted that staging was down;
    Cloudflare returned error 1033 (tunnel not connected) and SSH timed out for more than
    5 minutes.
  - The journal of that boot stops at 21:51:02 CET with nothing after it: no shutdown,
    out-of-memory, hung-task or soft-lockup messages. The VPS stayed frozen for about 80
    minutes until the owner rebooted it from the Contabo panel at 23:14 CET.
  - The server was nearly idle: the #583 test run had finished and cleaned up just
    before. The next test run failed at its first SSH step, so no test load was running
    during the freeze.
  - After the reboot, `api`, `cloudflared` and `litestream` came back by themselves and
    staging answered 200. Production on Fly was unaffected throughout.
  - **Decision needed before move day:** #602 records a go/no-go rule (7 consecutive days
    without an unplanned restart or freeze), the evidence to collect per incident, and
    the escalation order (another Contabo node, then a provider change).
- **Third incident: a longer silent freeze (night of 2026-11-01 to 11-02).**
  - The journal of the boot that started at 23:14 CET stops at 01:51:33 CET. The last
    lines are an SSH session logging out normally, with no system shutdown, out-of-memory,
    hung-task or soft-lockup messages after them.
  - The next boot was at 08:26 CET (`uptime -s`), so the VPS was down or frozen for about
    6.5 hours. Contabo restarted it, not the owner.
  - The server was idle: the #583 test containers had exited by about 00:46 CET, and no
    job was running.
  - The stack came back by itself again, and the finished test results survived on disk.
  - This restarts #602's 7-day window: the earliest date it can close is 2026-11-09, if
    nothing else happens.
  - The owner decided not to ask Contabo for another host node: Contabo is a temporary host
    until Hetzner or OVH have stock, so the incidents are logged and watched, not escalated.
- **What now holds.** The monitoring works: UptimeRobot caught the freeze within minutes,
  and Sentry is set up in the EU region (#592).
