#!/usr/bin/env bash
# Build the Flutter web app in release mode and upload it to Cloudflare Pages
# (direct upload; issues #129/#130, ADR 048). No credentials live in the repo:
# they come from your environment or from a private env file outside it
# (see docs/CLOUDFLARE_PAGES_SETUP.md and docs/DEPLOYMENT.md section 11).
#
#   scripts/deploy_web.sh            # production deploy
#   scripts/deploy_web.sh --preview  # deploy to a preview URL, production untouched
#
# Env file: MAYOS_WEB_ENV (default ~/.config/mayos/web.env) is sourced when it
# exists; variables already set in the shell take precedence. It holds:
#   CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID   (wrangler auth; optional when
#                                                 `npx wrangler login` is active)
#   GOOGLE_WEB_CLIENT_ID                          (Google sign-in button)
#   POSTHOG_CLIENT_KEY                            (public PostHog project key)
# Optional env: PAGES_PROJECT (default mayos), MAYOS_API_BASE_URL
# (default https://mayos-api.fly.dev; must match the CSP connect-src in
# mobile/web/_headers), PAGES_BRANCH (default main).
set -euo pipefail

env_file="${MAYOS_WEB_ENV:-$HOME/.config/mayos/web.env}"
if [[ -f "$env_file" ]]; then
  # Shell values win over the file, so one-off overrides still work.
  saved="$(export -p)"
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
  eval "$saved"
fi

cd "$(dirname "$0")/../mobile"

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]] && ! npx --yes wrangler@latest whoami >/dev/null 2>&1; then
  echo "error: set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID (Cloudflare Pages: Edit) or run 'npx wrangler login'." >&2
  exit 1
fi
project="${PAGES_PROJECT:-mayos}"
api_url="${MAYOS_API_BASE_URL:-https://mayos-api.fly.dev}"
branch="${PAGES_BRANCH:-main}"
[[ "${1:-}" == "--preview" ]] && branch="preview"

if [[ "$branch" == "main" ]]; then
  for name in GOOGLE_WEB_CLIENT_ID POSTHOG_CLIENT_KEY; do
    if [[ -z "${!name:-}" ]]; then
      echo "warning: $name is unset; this production build ships without it." >&2
    fi
  done
fi

if ! grep -qF "$api_url" web/_headers; then
  echo "error: $api_url is not in mobile/web/_headers; the CSP would block the API." >&2
  exit 1
fi

defines=(--dart-define="MAYOS_API_BASE_URL=$api_url")
[[ -n "${GOOGLE_WEB_CLIENT_ID:-}" ]] && defines+=(--dart-define="GOOGLE_WEB_CLIENT_ID=$GOOGLE_WEB_CLIENT_ID")
[[ -n "${POSTHOG_CLIENT_KEY:-}" ]] && defines+=(--dart-define="POSTHOG_CLIENT_KEY=$POSTHOG_CLIENT_KEY")

# Self-hosted CanvasKit and no service worker keep the CSP strict and reloads predictable.
flutter build web --release --no-web-resources-cdn --pwa-strategy=none "${defines[@]}"

npx --yes wrangler@latest pages deploy build/web \
  --project-name "$project" --branch "$branch" --commit-dirty=true
