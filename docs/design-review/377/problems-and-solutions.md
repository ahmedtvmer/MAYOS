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
| 11 | Ceiling of 11–12 req/s with half the CPU idle | Full program rebuild on every request, single GIL | #582 ✅ (+17% req/s); #583 ✅ program cache (about 30 req/s, more than twice #582; save 0.05 s at 20 Players) | ✅ fixed |
| 12 | Litestream CPU grows with the number of ledgers | A directory watch over every ledger | #600: Player ledgers use 10-second monitor and sync intervals; CPU growth addressed. Memory remains open in #616. | ✅ CPU addressed; memory open |
| 13 | The test suite can't run from a fresh clone | Git-ignored `db/catalog.db`, file-handle leak, no `git` in the image | #580 | ⏳ open |
| 14 | Two tests already failing on master | A clock-dependent test; `.conn` use in `service/injuries.py` | #581, merged in `3ea1a0b7` | ✅ |
| 15 | Long jobs ran without time limits or start checks | Orchestration mistakes | Process change | ✅ |
| 16 | The server hard-rebooted 6 times on 2026-11-01, then froze for about 80 minutes that evening, about 6.5 hours overnight, about 19 minutes and about 53 minutes on 2026-11-02 | Contabo host (patching per support; the freeze left no trace in the guest) | Stack restarts by itself; UptimeRobot and Sentry in place; go/no-go rule in #602 | ⏳ watching |

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
- **Fix, step 2 (#583, ADR 096, merged in `fc1e2315`).** Cache the active program per Player. SQLite triggers maintain a per-ledger and per-catalog revision (a random generation plus a counter), so any write from any code path invalidates the cache. The tables are additive, so there is no schema version bump and rollback stays available.
  - Reads get a read-only view; edits still get a fresh mutable copy. Nothing is stored inside a write transaction, so a rollback can't leave stale data, and every restore rotates the generation.
  - The two-model review (Opus 5.5 main, Sol 6.1 debate) agreed on six findings, all fixed with tests. The two that mattered: a workout save read the program before its write transaction, so a coach publish in between was recorded against the old version; and loads ran under a lock shared by all Players, so one slow miss stalled everyone. Sol added one: a restore could bring back an old counter that matched a cached, different program.
  - Verification on the server: full suite 142/146 (the 2 known no-git failures, and 2 in the new tests, fixed and rerun: 148 passed).
  - Same stepped test, same verified data copy, image `ee744d4ff6e6` (master `38452c6e` + #583; the merged tree is identical):

| Players | Req/s (#582 → #583) | Save median / p95 after | Save median #582 | Read median after | Errors | CPU idle |
| ---: | :--- | :--- | ---: | ---: | ---: | ---: |
| 20 | 14.1 → **18.4** | **0.05** / 0.20 s | 0.23 s | 0.06 s | 0 | 69% |
| 50 | 13.7 → **32.2** | **0.44** / 1.25 s | 2.51 s | 0.35 s | 0 | 52% |
| 100 | 12.6 → **30.7** | **2.17** / 2.79 s | 6.35 s | 1.94 s | 0 | 46% |
| 200 | 9.8 → **28.2** | **5.72** / 7.26 s | 17.1 s | 5.45 s | 0 | 39% |

  - **Result.** The ceiling rose from about 14 to about 30 req/s, more than twice as high, and stays there up to 200 Players (step 1 fell to 9.8). A save at 20 Players takes 0.05 s, and at 200 Players 5.7 s instead of 17 s. API memory stayed at about 400 MB with 215 ledgers cached. CPU is still 40–50% idle, so the single GIL is still the limit above about 30 req/s. Litestream now used 25–38% CPU during runs and 54% after (problem 12).
  - **What it means for monthly Players (estimate, 2026-11-02).** The trial measurement is unchanged (rehearsal copy of 2026-10-31):
    - The owner works out every 2.1 days, about 12 sets each.
    - Other trial Players average about 1 workout a week.
    - A training Player sends about 0.5 requests a minute.
    - Workout length is not measurable yet; #599 records it from now on.

    The model scales with the usable ceiling, about 2.2× #582's:

| Estimate | After #582 | After #583 |
| :--- | ---: | ---: |
| Players training at the same moment | about 1,200 | **about 2,600** |
| Monthly Players, all training like the owner | 6k–17k | **about 13k–37k** |
| Monthly Players, trial mix | 15k–40k | **about 33k–88k** |

  - **The ceiling is now backups, not requests.** These are request-capacity figures only. Litestream watches every ledger separately (problem 12). It already used 65% of a CPU idle at about 750 ledgers, so at a few thousand Players it would saturate the server long before the API does. #600 now sets the real monthly-Player ceiling and is the next capacity step. Above about 30 requests a second, the API's single worker (one GIL, CPU 40–50% idle) is the limit again.

### 12. Litestream CPU grows with the number of ledgers

Litestream 0.5 watches the ledger directory and monitors each database
separately. The staging rehearsal measured the following at 1, 10, and 30
second intervals (same Litestream 0.5.17 image for all variants):

| Users-dir interval | Idle CPU at 750 ledgers (avg / max) | Litestream CPU under 200-Player load (215 ledgers) | API req/s under load | Litestream memory at 750 ledgers |
| :--- | :--- | :--- | ---: | ---: |
| 1s (before) | 58.0% / 118.6% | 28.2% | 23.3 | 593 MiB |
| 10s | 23.1% / 59.2% | 20.1% | 24.8 | 563 MiB |
| 30s | 17.0% / 32.3% | 19.4% | 22.9 | 557 MiB |

Earlier 1-second idle readings were 1.7% CPU (27 MiB) at 15 ledgers and
13.8% (184 MiB) at 215 ledgers.

- **Decision (#600).** Set both the Player-ledger `monitor-interval` and
  replica `sync-interval` to 10 seconds, retaining `watch: true`. Catalog and
  deletion records keep their 1-second defaults. The Player-ledger recovery
  point is now about 10–20 seconds of newest writes (previously about 1–2
  seconds). An unsynced workout remains on the phone as an offline draft and
  retries when the app reconnects.
- **Status.** CPU growth addressed by #600. Memory is unaffected by interval
  tuning and remains open in #616.

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
- **Fourth incident: a silent stop at the start of a test run (2026-11-02, afternoon).**
  - The journal stops at 15:01:41 CET, 7 seconds after three test containers were started
    (`--cpus 1 --memory 2g` each). The memory was not used yet, and there are no
    out-of-memory, hung-task or soft-lockup messages.
  - Staging returned Cloudflare 530 and SSH timed out until the next boot at 15:20 CET
    (about 19 minutes). The stack came back by itself.
  - It matches the earlier silent freezes. This time it started under load, but the 21:51
    freeze on 2026-11-01 happened while idle, so the test run is not a proven cause.
  - The #602 window restarts again: the earliest it can close is 2026-11-09 15:20 CET.
- **Fifth incident: another stop at the start of a test run (2026-11-02, evening).**
  - The journal stops at 18:55:07 CET, about a minute after the first of three test
    containers started (the #517 full suite). There are no out-of-memory, hung-task or
    soft-lockup messages. The next boot was at 19:47 CET (about 53 minutes).
  - The last two incidents both began within a minute of starting three test containers
    at once, while earlier freezes happened while idle. The host is unstable either way,
    but a burst of container start-ups seems to trigger it. From now on, server test runs
    use one container at a time.
  - The #602 window restarts: the earliest it can close is 2026-11-09 19:47 CET.
- **What now holds.** The monitoring works: UptimeRobot caught the freeze within minutes,
  and Sentry is set up in the EU region (#592).
