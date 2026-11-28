#!/usr/bin/env bash
# Build the signed Android App Bundle for Google Play (#895).
#
#   scripts/build_android_release.sh [extra flutter build args...]
#
# Signing comes from mobile/android/key.properties (gitignored, see
# docs/PLAY_RELEASE.md §3-4). Build values come from the environment or from a
# private env file, MAYOS_ANDROID_ENV (default: .env at the repo root, which is
# gitignored); shell values win over the file. It holds:
#   GOOGLE_WEB_CLIENT_ID   Web OAuth client ID used as serverClientId
#   SENTRY_APP_DSN         DSN of the mayos-app Sentry project (never the
#                          server's SENTRY_DSN)
#   POSTHOG_CLIENT_KEY     optional public PostHog key
# Optional: MAYOS_API_BASE_URL (default https://api.mayos.online).
#
# The Sentry release is mayos-mobile@<versionName>+<versionCode>, read from
# mobile/pubspec.yaml, so every Play build reports under its own release.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
env_file="${MAYOS_ANDROID_ENV:-$repo_root/.env}"
if [[ -f "$env_file" ]]; then
  saved="$(export -p)"
  set -a
  # shellcheck disable=SC1090
  source <(tr -d '\r' < "$env_file")
  set +a
  eval "$saved"
fi

api_url="${MAYOS_API_BASE_URL:-https://api.mayos.online}"
app_dsn="${SENTRY_APP_DSN:-}"

if [[ -z "${GOOGLE_WEB_CLIENT_ID:-}" ]]; then
  echo "error: GOOGLE_WEB_CLIENT_ID is unset; Google sign-in would be hidden." >&2
  exit 1
fi
if [[ -z "$app_dsn" ]]; then
  echo "error: SENTRY_APP_DSN is unset; set the mayos-app project's DSN." >&2
  exit 1
fi
if [[ -n "${SENTRY_DSN:-}" && "$app_dsn" == "$SENTRY_DSN" ]]; then
  echo "error: SENTRY_APP_DSN equals the server SENTRY_DSN; use the mayos-app DSN." >&2
  exit 1
fi

version_line="$(grep -E '^version: ' "$repo_root/mobile/pubspec.yaml")"
version="${version_line#version: }"
version="${version//$'\r'/}"
release="mayos-mobile@${version}"

defines=(
  --dart-define="MAYOS_API_BASE_URL=$api_url"
  --dart-define="GOOGLE_WEB_CLIENT_ID=$GOOGLE_WEB_CLIENT_ID"
  --dart-define="SENTRY_DSN=$app_dsn"
  --dart-define="SENTRY_RELEASE=$release"
  --dart-define="SENTRY_ENVIRONMENT=production"
)
[[ -n "${POSTHOG_CLIENT_KEY:-}" ]] && defines+=(--dart-define="POSTHOG_CLIENT_KEY=$POSTHOG_CLIENT_KEY")

echo "Building $release against $api_url"
cd "$repo_root/mobile"
flutter build appbundle --release \
  -PappLinkHost="${api_url#https://}" \
  "${defines[@]}" "$@"
echo "Bundle: mobile/build/app/outputs/bundle/release/app-release.aab ($release)"
