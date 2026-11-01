# #377 rehearsal, part 1: Contabo server, data copy and load test (2026-10-31)

> Follow-up: every problem found in this rehearsal, its cause, fix and verification,
> and the load results after #578 are in [problems-and-solutions.md](problems-and-solutions.md).

The first part of the dress rehearsal for moving the production API from Fly.io to a
Contabo Cloud VPS (spec #571, ADR 072 amendment). Production stayed on Fly the whole
time: `api.mayos.online` answered 200 from Fly before, during and after.

## Server

| Item | Value |
| :--- | :--- |
| Plan | Contabo Cloud VPS, EU region (Germany): 4 vCPU (AMD EPYC), 7.8 GiB RAM, 96 GB disk, Ubuntu 24.04.5 |
| Host key | `SHA256:XdCO+KwcATwLW8vhxf3ejDWuupmliiAHLXhWkifbBbU`, confirmed in the provider's VNC console |
| Bootstrap | `deploy/setup_vps.sh` from a WSL checkout (Contabo's image already had an `ubuntu` sudo user) |
| SSH | Keys only; `root` and `ubuntu` refused; only `deploy` can log in |
| Firewall | UFW: only 22 open from outside; 80, 443 and 8000 closed |
| `deploy` sudo | `docker` and `sudoedit /opt/mayos/.env` only |
| Docker / Compose | 29.9.2 / v5.6.1 |
| Disk after two deploys | 5.5 GB used of 96 GB |

## Stack and network

| Item | Value |
| :--- | :--- |
| API image | `8a16014758bb` (commit `8a160147`); two tags kept for rollback |
| Services | `api` healthy · `cloudflared` 4 connections (Frankfurt) · `litestream` replicating to R2 `rehearsal/` |
| Cloudflare Tunnel | `mayos-prod`, one route: `staging.mayos.online → http://api:8000` (`api.` is added only on move day, #378) |
| Settings | 43 keys copied from Fly by name, never printed; values single-quoted for Compose |
| Rehearsal isolation | `SMTP_HOST` and `POSTHOG_API_KEY` empty, alert sweep and daily backup off, `LITESTREAM_R2_PREFIX=rehearsal` |

## Data copy

| Step | Result |
| :--- | :--- |
| Snapshot on Fly | SQLite online backup of `catalog.db`, `deletions.db` and 15 Training ledgers, plus migration snapshots and `manual-backups` (`backups/daily` excluded: already in R2) |
| Transfer | Fly → WSL → server; sha256 equal at every hop |
| `PRAGMA integrity_check` | 17 of 17 databases `ok` |
| Staging after restore | `/readyz` 200 through the Tunnel |

## Smoke tests

| Test | Result |
| :--- | :--- |
| Register and onboard a Player | ✅ 5.5 s |
| Workout save (owner PC → Cloudflare → server) | ✅ 4 of 4, median 468 ms, p95 500 ms |
| Program read | ✅ 403 ms |
| Chat streaming (hosted model) | ✅ 2 of 2, full reply about 5.3 s |
| 6th wrong login | ✅ `401 ×5 → 429` |
| Google sign-in, owner TOTP login with real IP in the audit log, reset link | ⏳ needs the owner in a browser |

## Load test

`scripts/load_test.py` (#576), think time 0.5–1.5 s (about one request per second per simulated
Player, like the 2026-10-07 Fly test), 90–120 s measured phase. Register and login limits
were raised on staging for the run and then restored to `5/minute`.

### Round 1: owner PC → Cloudflare → server

| Players | Req/s | Save median / p95 | Errors | Server CPU idle / steal |
| ---: | ---: | :--- | :--- | :--- |
| 20 | 5.6 | 2.66 s / 3.85 s | 1 × 502 | 27% / 0% |
| 50, 100, 200, 400 | — | — | 0 Players ready: registration plus program generation exceeded the client's 30 s timeout | 36–56% / 0% |

### Round 2: on the server, directly against `api:8000`, each run from a clean copy

| Run (20 Players) | Req/s | Save median / p95 | API CPU |
| :--- | ---: | :--- | ---: |
| Default threads, Litestream on | 4.8 | 3.1 s / 4.6 s | — |
| Default threads, Litestream off | 4.6 | 3.3 s / 5.6 s | 360% |
| `OMP_NUM_THREADS=1`, Litestream on | 3.4 | 4.9 s / 7.4 s | 444% |
| `OMP_NUM_THREADS=1`, Litestream off | 3.5 | 3.2 s / 5.1 s | 247% |

40 and 80 Players: no Player finished setup within 30 s.

### Single-core speed

| Benchmark | Fly `shared-cpu-1x` | Contabo |
| :--- | ---: | ---: |
| Python loop | 0.70 s | 0.89 s |
| sha256 chain | 0.20 s | 0.24 s |
| SQLite inserts and query | 0.66 s | 0.79 s |

### Litestream CPU

| Ledgers | Litestream CPU |
| ---: | :--- |
| 15 (real) | 2.5% idle |
| 140–155 | 62–100% idle after load |
| about 750 | 65% idle, 110% under load, 390 MB |

## Findings

1. **The API is the bottleneck, not the server.** At 20 Players the API used 3.5–4.4 of the 4
   cores to complete about 4.6 requests a second, roughly 0.8 CPU-seconds per request. The
   Contabo core is only 20–25% slower than Fly's, and neither Litestream nor
   `OMP_NUM_THREADS=1` changed throughput. Fly's 19 req/s figure is from 2026-10-07, before
   several features landed. Production was not load-tested to compare.
2. **The workout-save and program-read paths do not call the embedding model**, so switching
   ONNX back to PyTorch would not help them.
3. **Litestream CPU grows with the number of ledgers.** It is negligible at today's 15 and
   significant at a few hundred. It needs tuning before Player numbers grow.
4. **The load script starts every Player's setup at once**, so runs above 20 Players time out
   in registration and program generation rather than measuring steady load.

## Capacity estimate

- Simulated Players at one request per second: about 5 before requests queue; about 20 at
  multi-second latency.
- Real Players: a workout is saved once, at Finish, plus a few reads. At about one request
  per minute per training Player and about 3 req/s with low latency, that is roughly
  150–200 Players training at the same moment. This is an estimate, not a measurement; a
  real figure needs the profiling fix and a ramped load test.

## Incidents

| Event | Effect | Resolution |
| :--- | :--- | :--- |
| First bootstrap stopped on SIGPIPE; Windows line endings; scripts not executable | Setup could not finish | #575 |
| First deploy crashed at the history step and started only the API | Tunnel and Litestream down until started by hand | #577 |
| Staging route saved as `https://api:8000` | 502 on staging | Route changed to `http://api:8000` |
| The local data archive was deleted mid-rehearsal and the restore step ran without checking it | Staging ran on an empty database during one run; production unaffected | Fresh verified copy; restores now refuse unless the archive's sha256 matches |

## Still open in #377

- Owner browser checks: Google sign-in, TOTP admin login with real IP, password-reset link.
- Automatic-rollback exercise, and the restore drill from the `rehearsal/` replicas.
- Profiling the request hot path, then repeating the load test with ramp-up.
- UptimeRobot on `/readyz`.
- Wipe: test accounts, the copied data, the `rehearsal/` R2 prefix, the owner's
  `~/mayos-rehearsal`, and any Contabo snapshot taken after the data copy (within 30 days).
