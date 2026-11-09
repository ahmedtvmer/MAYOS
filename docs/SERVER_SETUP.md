# Production server setup

This checklist prepares MAYOS on a Contabo Cloud VPS behind a Cloudflare Tunnel.
It requires the owned domain and Cloudflare zone from #132. All hostnames are
configuration; this guide does not choose a domain.

## Owner steps

### 1. Order the server (Contabo)

1. Order a **Contabo Cloud VPS** in Contabo's EU region (Germany) with 4 vCPU,
   8 GB RAM, 100 GB SSD, Ubuntu 24.04, one IPv4 address, and a monthly term.
   Add the owner's SSH public key at order. Ubuntu 26.04 is also acceptable
   only when Docker's Ubuntu apt repository publishes a `Release` file for its
   codename; `server_bootstrap.sh` checks this before adding Docker's
   repository.
2. Skip Contabo's backup add-on: Litestream and R2 already cover backups. Skip
   private networking and extra IPs: the Cloudflare Tunnel needs no extra
   network. Note the server's public IP address.
3. Install OpenSSH, `rsync`, `nc`, and the AWS CLI (for the R2 object listing)
   on the machine that has this checkout. Windows owners must run setup and
   deploys from WSL (Ubuntu), using a checkout on the WSL filesystem (for
   example `~/MAYOS`) created with `git config --global core.autocrlf false`;
   never use a checkout under `/mnt/c`, `/mnt/f`, or another Windows drive.
   Install `rsync`, `nc`, and `ssh` from the WSL distribution's packages. Set
   `MAYOS_DEPLOY_HOST` in the
   environment or as an unquoted line in this checkout's ignored `.env`. This
   owner-machine value does not belong in `/opt/mayos/.env`.
4. The setup script defaults to `~/.ssh/id_ed25519.pub` and its matching
   private key. If the key added at order uses another path, set
   `SSH_PUBLIC_KEY_PATH` and `SSH_PRIVATE_KEY_PATH` when running the script.

### 2. Prepare the bootstrap account

Contabo's Ubuntu image logs in as `root`. Sign in from the owner machine using
the key added at order, then, as root, check whether cloud-init already created
an `ubuntu` user with passwordless sudo:

```bash
id ubuntu
```

If the user exists, install the owner's public key in
`/home/ubuntu/.ssh/authorized_keys`, owned by `ubuntu` and mode `0600`. If it
does not exist, create the non-root `ubuntu` account that `setup_vps.sh`
expects, give it passwordless sudo, and install the key as follows:

```bash
adduser --disabled-password --gecos '' ubuntu
usermod -aG sudo ubuntu
printf 'ubuntu ALL=(ALL) NOPASSWD:ALL\n' >/etc/sudoers.d/ubuntu
chmod 0440 /etc/sudoers.d/ubuntu
install -d -o ubuntu -g ubuntu -m 0700 /home/ubuntu/.ssh
install -o ubuntu -g ubuntu -m 0600 /dev/null /home/ubuntu/.ssh/authorized_keys
cat >>/home/ubuntu/.ssh/authorized_keys
```

Paste the owner's public key as one line, then press Ctrl-D. Verify key login
and sudo access as `ubuntu` before continuing. `setup_vps.sh` then runs as
normal; its final hardening removes this bootstrap key after installing the
owner key for `deploy`.

### 3. Provision the server

From the repository root, run with `MAYOS_DEPLOY_HOST` set in the environment
or checkout `.env`:

```bash
./deploy/setup_vps.sh
```

You can also pass the public IP directly: `./deploy/setup_vps.sh 203.0.113.10`.
`MAYOS_BOOTSTRAP_USER` defaults to `ubuntu`; set it only if the image uses a
different non-root sudo account. Over SSH, the script runs
`deploy/server_bootstrap.sh` with sudo. The bootstrap installs Docker Engine,
the Compose plugin, `unattended-upgrades`, and UFW; creates the `deploy`
account; and prepares `/opt/mayos` and `/mnt/mayos-data/data` on the VPS local
disk. `/mnt/mayos-data/data` is a plain local directory whose name is retained
from the old volume design so the Compose file stays unchanged. The data
directory is root-owned because `Dockerfile.fly` has no `USER` directive and
both containers run as root. Compose binds only that directory and refuses to
create it if missing.

UFW defaults to deny incoming and allow outgoing. Bootstrap reads the SSH port
from `sshd -T` (falling back to 22), allows that TCP port before enabling UFW,
and does not reset existing rules; reruns therefore keep owner-added rules.
Docker is installed after the firewall is enabled. The Compose stack publishes
no ports: the API uses `expose` only, while `cloudflared` dials out through the
Tunnel. Docker can bypass UFW for published ports, so never add a Compose
`ports:` entry.

The bootstrap writes `/opt/mayos/state/.bootstrap-complete` as its last step.
Setup hardens SSH and removes the bootstrap user's `authorized_keys` in one
final root step, then writes the world-readable
`/opt/mayos/state/.setup-complete` marker. Deploy SSH and Docker access are
verified before SSH settings change and again after reload. SSH is restricted
to key authentication, with root login disabled. The `ubuntu` account remains
on the host with sudo access; use the provider's web console (Contabo: VNC
console in the customer panel) for host-level repairs. Over SSH, only `deploy`
can log in.
`deploy` is not in the `docker` group; use `sudo docker compose ...` for Docker
commands and `sudoedit /opt/mayos/.env` to edit the root-owned file.

Setup uses the deploy-only path only when `.setup-complete` exists and Docker
Compose works. If that marker is absent, it uses the still-authorized bootstrap
user, re-applies the idempotent bootstrap, verifies deploy access, then
re-hardens SSH and removes the bootstrap key.

If `/opt/mayos/state` or its setup marker is lost after a completed setup, the
bootstrap SSH key has already been removed. Use the provider's web console
(Contabo: VNC console in the customer panel) to restore the bootstrap user's
authorized key with the owner's public key, then rerun setup
so it recreates the state directory and markers. With the default user, run
these commands in the console and paste the owner's public key as one line
when `sudoedit` opens the file:

```bash
sudo install -d -o ubuntu -g ubuntu -m 0700 /home/ubuntu/.ssh
sudo install -o ubuntu -g ubuntu -m 0600 /dev/null /home/ubuntu/.ssh/authorized_keys
sudoedit /home/ubuntu/.ssh/authorized_keys
sudo chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys
sudo chmod 0600 /home/ubuntu/.ssh/authorized_keys
```

Use the configured home and account name instead if `MAYOS_BOOTSTRAP_USER` is
not `ubuntu`.

The server address is available as `MAYOS_DEPLOY_HOST`. The Compose command and
layout are fixed for the deploy script in #376:

- `/opt/mayos/app`: rsynced checkout/build input, owned by `deploy`.
- `/opt/mayos/app/deploy/.image.env`: deploy-owned Compose interpolation env
  file containing the selected `MAYOS_IMAGE_TAG`.
- `/opt/mayos/state`: deploy-owned deployment history, outside the rsynced tree.
- `/opt/mayos/.env`: root-owned, mode `0600`.
- `/mnt/mayos-data/data`: root-owned application data directory on the VPS's
  local disk.
- Run Compose with
  `sudo docker compose -f /opt/mayos/app/deploy/compose.server.yaml --env-file /opt/mayos/.env --env-file /opt/mayos/app/deploy/.image.env -p mayos ...`.

Contabo includes one snapshot. Take it right after setup completes, **before
any Player data is on the server**. A snapshot is a full disk copy. If a
snapshot is made after Player data exists, delete it within 30 days to meet
ADRs 015 and 044.

### 4. Create the Cloudflare Tunnel

In the Cloudflare Zero Trust dashboard, create a remotely managed Tunnel and
copy its token. Under its public hostnames, add both
`MAYOS_STAGING_HOSTNAME` and `MAYOS_API_HOSTNAME`; point each hostname at
`http://api:8000`. The Tunnel container and API share the Compose network, so
`api` is the service address. Keep the token private and put it only in the
server `.env` as `TUNNEL_TOKEN`.

Set these hostname values in `/opt/mayos/.env`:

```dotenv
MAYOS_API_HOSTNAME=api.example.com
MAYOS_STAGING_HOSTNAME=staging.example.com
```

Replace both example hostnames with the actual hostnames. The staging hostname
is for the owner verification; installed clients use the API hostname. Set each
as a hostname only, without `https://`.

### 5. Migrate runtime settings and secrets

Before stopping the Fly Machine, inspect its application environment with
`fly ssh console -C printenv`. It displays secret values: use a private,
non-recorded terminal, never echo or paste values into notes, issues, logs, or
chat, and do not commit the output. Copy every currently configured
application variable into `/opt/mayos/.env`; omit unset optional variables.
Use this repository-derived name list as a checklist, and preserve any other
configured application variable unless it is Fly-specific or set by Compose.

- Required credentials and backup: `JWT_SECRET`, `LLM_API_KEY`, `R2_ENDPOINT`,
  `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. **Copy `JWT_SECRET`
  unchanged**; generating a new value invalidates existing signed tokens and
  email-hash keys.
- Email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, `SMTP_USER`,
  `SMTP_PASSWORD`, `SMTP_FROM`.
- Google sign-in: `GOOGLE_WEB_CLIENT_ID`.
- Owner dashboard and alerts: `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`,
  `ADMIN_TOTP_SECRET`, `OWNER_ALERT_EMAIL`.
- Analytics: `POSTHOG_API_KEY`, `POSTHOG_HOST`, `POSTHOG_PERSONAL_API_KEY`,
  `POSTHOG_PROJECT_ID`, `POSTHOG_API_HOST`.
- App links and public contact: `ANDROID_APP_PACKAGE`,
  `ANDROID_APP_SHA256_CERT_FINGERPRINTS`, `ANDROID_STORE_URL`,
  `PRIVACY_CONTACT_EMAIL`, `MIN_ANDROID_BUILD`.
- Model endpoint and roles: `LLM_API_BASE`, `LLM_MODEL`, `LLM_MAX_TOKENS`,
  `LLM_MAX_CONCURRENT`, `LLM_TEMPERATURE`, `LLM_EXTRA_BODY`, `LLM_ENABLE_THINKING`,
  `JUDGE_MODEL`, `JUDGE_MAX_TOKENS`, `JUDGE_EXTRA_BODY`, `COACH_MODEL`,
  `COACH_MAX_TOKENS`, `COACH_EXTRA_BODY`, `LLM_REQUEST_TIMEOUT`,
  `LLM_MAX_RETRIES`, `LLM_STREAM_CHUNK_TIMEOUT`, `MODEL_DEVICE`,
  `EMBEDDING_MODEL`, `OMP_NUM_THREADS`.
- Product and model limits: `MAYOS_ENV`, `MAYOS_RELEASE_PHASE`,
  `COACH_CLOSED_TRIAL_OVERRIDE`, `MODEL_RATE_LIMIT_REQUESTS`,
  `MODEL_DAILY_TOKEN_LIMIT`, `MODEL_PRICING_JSON`, `MODEL_SPEND_ALERT_USD`,
  `COACH_AI_ENABLED`, `COACH_AI_EVAL_REPORT`, `COACH_ROSTER_AI_ENABLED`,
  `COACH_ROSTER_AI_EVAL_REPORT`, `CHECKPOINT_REVIEW_AI_ENABLED`,
  `CHECKPOINT_REVIEW_EVAL_REPORT`.
- Request limits: `RATE_LIMIT_LOGIN`, `RATE_LIMIT_REGISTER`,
  `RATE_LIMIT_USERNAME_CHECK`, `RATE_LIMIT_PASSWORD`, `RATE_LIMIT_RESET`,
  `RATE_LIMIT_CHAT`, `RATE_LIMIT_ONBOARDING`, `RATE_LIMIT_PROGRAM_MUTATE`,
  `RATE_LIMIT_COACH_INVITE`, `RATE_LIMIT_ASSIGNMENT_INVITE`,
  `RATE_LIMIT_ASSIGNMENT_PREVIEW`, `RATE_LIMIT_ASSIGNMENT_REDEEM`,
  `RATE_LIMIT_ASSIGNMENT_MUTATE`, `RATE_LIMIT_COACH_ASSISTANT`,
  `RATE_LIMIT_WORKOUT_SYNC_FAILURE`.
- Recovery and scheduling: `JWT_EXPIRY_HOURS`, `JWT_REMEMBER_ME_HOURS`,
  `RESET_TOKEN_TTL_MINUTES`, `EMAIL_VERIFICATION_CODE_TTL_MINUTES`,
  `COACH_INVITE_TTL_MINUTES`, `ASSIGNMENT_INVITE_TTL_MINUTES`,
  `ADMIN_RESET_LINK_TTL_MINUTES`, `MAYOS_DAILY_BACKUP_INTERVAL_SECONDS`,
  `MAYOS_ALERT_SWEEP_INTERVAL_SECONDS`, `MAYOS_BACKUP_RETENTION_DAYS`.
- App settings: `API_BASE_URL`, `UI_BASE_URL`, `HF_HOME`,
  `MAYOS_DELETIONS_DB`, `SKIP_LLM_LOAD`.

`POSTHOG_CLIENT_KEY` is a client release-build define, not an API server
setting; do not copy it into `/opt/mayos/.env`.

The `RESET_LINK_BASE_URL` value must change to
`https://${MAYOS_API_HOSTNAME}`. Compose derives that value from
`MAYOS_API_HOSTNAME`; do not copy the Fly hostname. Keep current non-secret
application settings that are still needed, such as `UI_BASE_URL`,
`MIN_ANDROID_BUILD`, model limits, and model configuration. The current Fly
configuration also sets `MAYOS_ENV=production`,
`COACH_AI_ENABLED=true`, and
`COACH_AI_EVAL_REPORT=/app/reports/coach_ai_eval.json`; carry these over if they
remain the intended production settings.

Coach roster questions (#311) have their own opt-in settings and report gate:
keep `COACH_ROSTER_AI_ENABLED=false` until
`COACH_ROSTER_AI_EVAL_REPORT=/app/reports/coach_roster_ai_eval.json` points to a
passing live report for the current roster prompt and Coach model.

Add the production values below. The #376 deploy script writes
`MAYOS_IMAGE_TAG` to `/opt/mayos/app/deploy/.image.env` for each Compose command;
do not set it in the root-owned secrets file. Keep
`LITESTREAM_R2_PREFIX=litestream` unless the existing R2 namespace has a
different production prefix. The same prefix must be used by Litestream,
account-deletion cleanup, and restore tooling.

```dotenv
LITESTREAM_R2_PREFIX=litestream
TUNNEL_TOKEN=YOUR_CLOUDFLARE_TUNNEL_TOKEN
```

Do not copy any `FLY_*` variable, Fly's generated environment, or the Fly-only
`FLY_APP_NAME` into the server `.env`. Compose sets
`MAYOS_DATA_DIR=/data`, `MAYOS_REQUIRE_PERSISTENT_DATA=true`,
`MAYOS_CLIENT_IP_HEADER=cf-connecting-ip`, and `MAYOS_LITESTREAM=true` for the
API. It also sets `RESET_LINK_BASE_URL` from `MAYOS_API_HOSTNAME`.

The file must remain root-owned and mode `0600`. Do not add it to the checkout
or send it through the #376 rsync step; it stays at `/opt/mayos/.env` on the
server. Also exclude the repository-root `.env` from rsync. `.dockerignore`
keeps that file out of the image build context as well.

### 6. Deploy and verify

From the main checkout, run `./deploy/deploy_server.sh`. The script fetches
`origin/master` and refuses unless HEAD equals it. It refuses linked worktrees and warns if
the checkout has uncommitted changes. See the [deployment runbook](DEPLOYMENT.md)
for deploy, status, and rollback commands. Compose builds
`mayos-api:${MAYOS_IMAGE_TAG}` on the server from the rsynced checkout using
`Dockerfile.fly`. The API runs one Uvicorn worker and publishes no host port;
`cloudflared` sends requests to `api:8000`, and Litestream reads
`deploy/litestream.yml` from the checkout.

Before deploying, ensure the checkout has `data/processed_exercises.csv`;
`Dockerfile.fly` copies this operator-provided seed file into the image.
For the #377 restore/copy rehearsal, stop both API and Litestream before
restoring or replacing data. Copy the contents of the restored `/data-restore`
directory to the host directory `/mnt/mayos-data/data`, then start the services;
Compose binds that directory to `/data` in both containers.
After deploying to the new server, set these values on the owner machine and
run the checks:

```bash
export MAYOS_DEPLOY_HOST=YOUR_SERVER_IPV4
export MAYOS_STAGING_HOSTNAME=staging.example.com
export SSH_PRIVATE_KEY_PATH="$HOME/.ssh/id_ed25519"

curl -fsS "https://${MAYOS_STAGING_HOSTNAME}/readyz"
ssh -i "$SSH_PRIVATE_KEY_PATH" "deploy@$MAYOS_DEPLOY_HOST" \
  'stat -c "%U:%G %a %n" /mnt/mayos-data/data'
ssh -i "$SSH_PRIVATE_KEY_PATH" "deploy@$MAYOS_DEPLOY_HOST" \
  'sudo docker compose -f /opt/mayos/app/deploy/compose.server.yaml --env-file /opt/mayos/.env --env-file /opt/mayos/app/deploy/.image.env -p mayos ps'
ssh -i "$SSH_PRIVATE_KEY_PATH" "deploy@$MAYOS_DEPLOY_HOST" \
  'sudo docker compose -f /opt/mayos/app/deploy/compose.server.yaml --env-file /opt/mayos/.env --env-file /opt/mayos/app/deploy/.image.env -p mayos logs --since=30m litestream'
ssh -i "$SSH_PRIVATE_KEY_PATH" "deploy@$MAYOS_DEPLOY_HOST" 'sudo ss -tlnp'
```

Confirm `/readyz` returns success through the staging hostname, the Litestream
logs show replication activity, and R2 contains the `catalog.db/`,
`deletions.db/`, and any created Training ledger replicas under
`LITESTREAM_R2_PREFIX`. On a trusted operator machine with the R2 environment
variables set securely (do not echo their values), list the objects with AWS
CLI:

```bash
AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
aws --region auto --endpoint-url "$R2_ENDPOINT" s3 ls \
  "s3://$R2_BUCKET/$LITESTREAM_R2_PREFIX/" --recursive
```

From outside the server, confirm that only SSH is open: the SSH check must
succeed, and each web/API port check must fail to connect.

```bash
nc -zvw3 "$MAYOS_DEPLOY_HOST" 22
nc -zvw3 "$MAYOS_DEPLOY_HOST" 80
nc -zvw3 "$MAYOS_DEPLOY_HOST" 443
nc -zvw3 "$MAYOS_DEPLOY_HOST" 8000
```

In `ss -tlnp`, the only listener bound to a public address should be SSH on
port 22; port 8000 must not appear as a host listener. Cloudflare Tunnel
traffic is outbound from `cloudflared`.

The server's `/mnt/mayos-data/data` directory is on its local disk, with no
separate volume. Durability rests on that disk plus Litestream's continuous R2
replication and the daily R2 snapshots. Player ledgers use 10-second monitor
and sync intervals, so about 10–20 seconds of a Player's newest writes can be
lost if the server dies; catalog and deletion records retain 1-second defaults.

### Pre-cutover load test

Before move day, run `scripts/load_test.py` against the staging hostname on a
copy of production data, as part of the #377 rehearsal. Step up from 20 to 50
to 100 Players, reusing the accounts created in the first step and staggering
each measured phase:

```sh
for players in 20 50 100; do
  python scripts/load_test.py --base-url "https://${MAYOS_STAGING_HOSTNAME}" \
    --players "$players" --setup-concurrency 5 --ramp-up 30 \
    --reuse-accounts
done
```

It passes only if it beats Fly's 19 requests/s and 1.3 s median workout save. If it fails, check CPU
steal (`%st` in `top`) and ask Contabo to move the VPS to another host. If it
still fails, stay on Fly.

### Move day: privacy policy

As part of the #378/#573 cutover, replace the current server-location sentence,
which spans lines 14–15 of `docs/PRIVACY_POLICY.md`, as a whole with:

> The service runs on a single server in Germany (Contabo) and is served over https from the address of this page.

Set `POLICY_VERSION` in `service/privacy_policy.py` to the next minor version
after the one live on move day (1.9 → 1.10 at the time of writing), and set
`POLICY_EFFECTIVE_DATE` to the move day. Deploy both policy changes with the
cutover.
