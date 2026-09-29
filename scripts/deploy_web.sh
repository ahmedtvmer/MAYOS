#!/usr/bin/env bash
# Build the Flutter web app in release mode and upload it to Cloudflare Pages
# (direct upload; issues #129/#130, ADR 048). No credentials live in the repo:
# CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID come from your environment
# (see docs/CLOUDFLARE_PAGES_SETUP.md).
#
#   scripts/deploy_web.sh            # production deploy
#   scripts/deploy_web.sh --preview  # deploy to a preview URL, production untouched
#
# Optional env: PAGES_PROJECT (default mayos), MAYOS_API_BASE_URL
# (default https://mayos-api.fly.dev; must match the CSP connect-src in
# mobile/web/_headers), GOOGLE_WEB_CLIENT_ID, PAGES_BRANCH (default main).
set -euo pipefail

cd "$(dirname "$0")/../mobile"

: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN (Cloudflare Pages: Edit)}"
: "${CLOUDFLARE_ACCOUNT_ID:?set CLOUDFLARE_ACCOUNT_ID}"
project="${PAGES_PROJECT:-mayos}"
api_url="${MAYOS_API_BASE_URL:-https://mayos-api.fly.dev}"
branch="${PAGES_BRANCH:-main}"
[[ "${1:-}" == "--preview" ]] && branch="preview"

if ! grep -qF "$api_url" web/_headers; then
  echo "error: $api_url is not in mobile/web/_headers; the CSP would block the API." >&2
  exit 1
fi

defines=(--dart-define="MAYOS_API_BASE_URL=$api_url")
[[ -n "${GOOGLE_WEB_CLIENT_ID:-}" ]] && defines+=(--dart-define="GOOGLE_WEB_CLIENT_ID=$GOOGLE_WEB_CLIENT_ID")

# Self-hosted CanvasKit and no service worker keep the CSP strict and reloads predictable.
flutter build web --release --no-web-resources-cdn --pwa-strategy=none "${defines[@]}"

npx --yes wrangler@latest pages deploy build/web \
  --project-name "$project" --branch "$branch" --commit-dirty=true
