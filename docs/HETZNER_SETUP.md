# Hetzner production setup

This checklist provisions MAYOS on one Hetzner Cloud server behind a
Cloudflare Tunnel. It requires the owned domain and Cloudflare zone from #132.
All hostnames are configuration; this guide does not choose a domain.

## Owner steps

### 1. Prepare the Hetzner project

1. Create a Hetzner account, add a payment method, and create a Cloud project.
2. Check the current [CX23 price](https://www.hetzner.com/cloud) and choose
   Falkenstein (`fsn1`) or Nuremberg (`nbg1`). The server and volume must use
   the same location.
3. Install the [Hetzner Cloud CLI](https://github.com/hetznercloud/cli),
   `jq`, OpenSSH, `nc`, and the AWS CLI (for the R2 object listing) on the
   machine that has this checkout.
4. Create an API token with Read & Write permissions in the Cloud project.
   Add it to the ignored repository-root `.env` as an unquoted line, and keep
   that file private (`chmod 600 .env`):

   ```dotenv
   HCLOUD_TOKEN=YOUR_HETZNER_API_TOKEN
   ```

   The setup script reads this value without sourcing or printing the file.
   For the later manual `hcloud firewall describe` check, configure the CLI
   context or set `HCLOUD_TOKEN` in that shell without echoing it.

5. Create an SSH key if needed. The setup script defaults to
   `~/.ssh/id_ed25519.pub` and its matching private key. It uploads only the
   public key to Hetzner and installs that key for `deploy`.

### 2. Provision the server

From any directory in this checkout, run:

```bash
bash deploy/setup_hetzner.sh
```

The defaults are `fsn1`, `cx23`, `ubuntu-24.04`, a 10 GB ext4 volume, and the
resource names `mayos-api`, `mayos-data`, and `mayos-fw`. The script reuses
resources with those names and refuses to reuse a firewall with unexpected
inbound rules or a volume attached to a different server. To choose Nuremberg,
run `HCLOUD_LOCATION=nbg1 bash deploy/setup_hetzner.sh`. Other supported
overrides are `HCLOUD_SERVER_TYPE`, `HCLOUD_IMAGE`, `HCLOUD_VOLUME_SIZE`,
`HCLOUD_SERVER_NAME`, `HCLOUD_VOLUME_NAME`, `HCLOUD_FIREWALL_NAME`,
`HCLOUD_SSH_KEY_NAME`, `SSH_PUBLIC_KEY_PATH`, `SSH_PRIVATE_KEY_PATH`, and
`HCLOUD_ENV_FILE`. `HCLOUD_TOKEN` may instead be exported in the environment.

The script creates or reuses a firewall with inbound TCP 22 only, creates the
server and ext4 volume, and attaches the volume using Hetzner's automount. It
mounts the volume root at `/mnt/mayos-data` by filesystem UUID, then creates
`/mnt/mayos-data/data` on that verified mount. The fstab entry uses `nofail`
and a 30-second device timeout so a missing volume does not block boot or SSH.
Compose binds only the `data` subdirectory and refuses to create it if it is
missing. Over SSH the script installs Docker Engine and the Compose plugin from
Docker's apt repository, enables `unattended-upgrades`, creates the `deploy`
account, and prepares `/opt/mayos`. It verifies the deploy key before disabling
password, keyboard-interactive, and root SSH login. `deploy` is not in the
`docker` group; use `sudo docker compose ...` for Docker commands and
`sudoedit /opt/mayos/.env` to edit the root-owned file.

The script tries one deploy-key SSH connection first. When it succeeds, the
server bootstrap is skipped and only `sudo docker compose version` is checked.
Thus rerunning after SSH hardening does not reapply the root bootstrap. If a
host-level bootstrap setting needs repair later, use Hetzner's web console for
a root shell and repair it there; the setup script will not enable public root
SSH again. For a server created by the earlier bootstrap revision, remove its
old Docker-group membership from that root shell with
`gpasswd --delete deploy docker`.

Save the server's IPv4 address printed at the end. The Compose command and
layout are fixed for the deploy script in #376:

- `/opt/mayos/app`: rsynced checkout/build input, owned by `deploy`.
- `/opt/mayos/.env`: root-owned, mode `0600`.
- `/mnt/mayos-data`: Hetzner volume mount root; application files live in
  `/mnt/mayos-data/data`.
- Run Compose with
  `sudo docker compose -f /opt/mayos/app/deploy/compose.hetzner.yaml --env-file /opt/mayos/.env -p mayos ...`.

### 3. Create the Cloudflare Tunnel

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

### 4. Migrate runtime settings and secrets

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
  `COACH_AI_ENABLED`, `COACH_AI_EVAL_REPORT`, `CHECKPOINT_REVIEW_AI_ENABLED`,
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

Add the Hetzner-specific values below. Set `MAYOS_IMAGE_TAG` to the full commit
that #376 is deploying; it is required and has no implicit `latest` fallback.
Keep `LITESTREAM_R2_PREFIX=litestream` unless the existing R2 namespace has a
different production prefix. The same prefix must be used by Litestream,
account-deletion cleanup, and restore tooling.

```dotenv
MAYOS_IMAGE_TAG=FULL_GIT_COMMIT
LITESTREAM_R2_PREFIX=litestream
TUNNEL_TOKEN=YOUR_CLOUDFLARE_TUNNEL_TOKEN
```

Do not copy `HCLOUD_TOKEN`, any `FLY_*` variable, Fly's generated environment,
or the Fly-only `FLY_APP_NAME` into the server `.env`. Compose sets
`MAYOS_DATA_DIR=/data`, `MAYOS_REQUIRE_PERSISTENT_DATA=true`,
`MAYOS_CLIENT_IP_HEADER=cf-connecting-ip`, and `MAYOS_LITESTREAM=true` for the
API. It also sets `RESET_LINK_BASE_URL` from `MAYOS_API_HOSTNAME`.

The file must remain root-owned and mode `0600`. Do not add it to the checkout
or send it through the #376 rsync step; it stays at `/opt/mayos/.env` on the
server. Also exclude the repository-root `.env` from rsync: it contains the
local `HCLOUD_TOKEN`. `.dockerignore` keeps that file out of the image build
context as well.

### 5. Deploy and verify

Use the deploy command in the [deployment runbook](DEPLOYMENT.md) after #376 is
available. Compose builds `mayos-api:${MAYOS_IMAGE_TAG}` on the server from the
rsynced checkout using `Dockerfile.fly`. The API runs one Uvicorn worker and
publishes no host port; `cloudflared` sends requests to `api:8000`, and
Litestream reads `deploy/litestream.yml` from the checkout.

Before deploying, ensure the checkout has `data/processed_exercises.csv`;
`Dockerfile.fly` copies this operator-provided seed file into the image.
For the #377 restore/copy rehearsal, stop both API and Litestream before
restoring or replacing data. Copy the contents of the restored `/data-restore`
directory to the host directory `/mnt/mayos-data/data` (not the volume mount
root), then start the services; Compose binds that directory to `/data` in
both containers.
After deploying to the empty volume, set these values on the owner machine and
run the checks:

```bash
export MAYOS_SERVER_IP=YOUR_SERVER_IPV4
export MAYOS_STAGING_HOSTNAME=staging.example.com
export SSH_PRIVATE_KEY_PATH="$HOME/.ssh/id_ed25519"

curl -fsS "https://${MAYOS_STAGING_HOSTNAME}/readyz"
ssh -i "$SSH_PRIVATE_KEY_PATH" "deploy@$MAYOS_SERVER_IP" \
  'findmnt --output SOURCE,UUID,TARGET --mountpoint /mnt/mayos-data'
ssh -i "$SSH_PRIVATE_KEY_PATH" "deploy@$MAYOS_SERVER_IP" \
  'sudo docker compose -f /opt/mayos/app/deploy/compose.hetzner.yaml --env-file /opt/mayos/.env -p mayos ps'
ssh -i "$SSH_PRIVATE_KEY_PATH" "deploy@$MAYOS_SERVER_IP" \
  'sudo docker compose -f /opt/mayos/app/deploy/compose.hetzner.yaml --env-file /opt/mayos/.env -p mayos logs --since=30m litestream'
ssh -i "$SSH_PRIVATE_KEY_PATH" "deploy@$MAYOS_SERVER_IP" 'sudo ss -tlnp'
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

From outside the server, confirm SSH is reachable and the web/API ports are
closed. Run the `hcloud` command from a shell configured with the project token.
Do not echo the token. The SSH check must succeed; each port check must fail to
connect:

```bash
nc -zvw3 "$MAYOS_SERVER_IP" 22
nc -zvw3 "$MAYOS_SERVER_IP" 80
nc -zvw3 "$MAYOS_SERVER_IP" 443
nc -zvw3 "$MAYOS_SERVER_IP" 8000
hcloud firewall describe mayos-fw
```

In `ss -tlnp`, the only listener bound to a public address should be SSH on
port 22; port 8000 must not appear as a host listener. Cloudflare Tunnel
traffic is outbound from `cloudflared`.
