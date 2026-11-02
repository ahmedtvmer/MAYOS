#!/usr/bin/env bash
# Deploy from the main checkout or restart one of the last three kept images.
# Usage: deploy/deploy_server.sh [deploy|rollback <commit>|status|pull <commit>]
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly IMAGE_TAG_RE='^[0-9a-f]{7,64}(-[0-9]{14}-[0-9]{1,5})?$'
readonly REMOTE_PREAMBLE=$'set -euo pipefail\nreadonly IMAGE_TAG_RE="^[0-9a-f]{7,64}(-[0-9]{14}-[0-9]{1,5})?$"\ncompose=(sudo docker compose -f /opt/mayos/app/deploy/compose.server.yaml --env-file /opt/mayos/.env --env-file /opt/mayos/app/deploy/.image.env -p mayos)\n'

usage() {
  cat <<'USAGE'
Usage:
  deploy/deploy_server.sh [deploy]
  deploy/deploy_server.sh rollback <commit>
  deploy/deploy_server.sh status
  deploy/deploy_server.sh pull <commit>

MAYOS_DEPLOY_HOST may be set in the environment or in the checkout's .env.
Run from the main checkout; a linked git worktree is refused.
On the server, pull <commit> fetches and verifies a public master commit before building.
USAGE
}

die() {
  printf 'deploy_server: %s\n' "$1" >&2
  exit 1
}

resolve_host() {
  local env_line
  local configured_host="${MAYOS_DEPLOY_HOST:-}"
  if [[ -z "$configured_host" && -f "$repo_root/.env" ]]; then
    while IFS= read -r env_line || [[ -n "$env_line" ]]; do
      case "$env_line" in
        MAYOS_DEPLOY_HOST=*)
          configured_host="${env_line#MAYOS_DEPLOY_HOST=}"
          configured_host="${configured_host%$'\r'}"
          break
          ;;
      esac
    done < "$repo_root/.env"
  fi
  [[ "$configured_host" =~ ^[A-Za-z0-9._:-]+$ && "$configured_host" != -* ]] ||
    die "set MAYOS_DEPLOY_HOST to the server IP or hostname (environment or checkout .env)"
  printf '%s' "$configured_host"
}

warn_if_dirty() {
  if [[ -n "$(git -C "$repo_root" status --porcelain --untracked-files=all)" ]]; then
    printf 'Warning: checkout has uncommitted changes; the build includes them.\n' >&2
  fi
}

remote_bash() {
  local -a remote_args=("$@")
  local remote_command="bash -s --"
  local preamble="$REMOTE_PREAMBLE"
  local pull_root="${server_root:-${MAYOS_SERVER_ROOT:-/opt/mayos}}"
  local pull_checkout="${server_checkout:-${MAYOS_SERVER_CHECKOUT:-$pull_root/src}}"
  local arg
  if [[ "${server_pull_mode:-0}" == 1 ]]; then
    preamble="set -euo pipefail
readonly IMAGE_TAG_RE='^[0-9a-f]{7,64}(-[0-9]{14}-[0-9]{1,5})?$'
compose=(sudo docker compose -f $pull_checkout/deploy/compose.server.yaml --env-file $pull_root/.env --env-file $pull_root/app/deploy/.image.env -p mayos)
"
  fi
  for arg in "${remote_args[@]}"; do
    printf -v arg '%q' "$arg"
    remote_command+=" $arg"
  done
  if [[ "${server_pull_mode:-0}" == 1 ]]; then
    { printf '%s' "$preamble"; cat; } | bash -s -- "${remote_args[@]}"
  else
    { printf '%s' "$preamble"; cat; } | ssh "$ssh_target" "$remote_command"
  fi
}

refuse_pull() { printf 'Deployment refused: %s\n' "$1"; exit 1; }

verify_required_checks() {
  local sha="$1" api_url checks required name
  api_url="${MAYOS_CHECK_RUNS_URL:-https://api.github.com/repos/ahmedtvmer/MYOS/commits/$sha/check-runs?per_page=100}"
  checks="$(curl --fail --silent --show-error --retry 0 -H 'Accept: application/vnd.github+json' "$api_url" 2>&1)" || refuse_pull "GitHub check-runs API failed: $checks"
  required="${MAYOS_REQUIRED_CHECKS:-Unit, Concurrency & Telemetry Tests|Production Image Smoke Test}"
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    CHECKS_JSON="$checks" CHECK_NAME="$name" python3 -c 'import json,os,sys; d=json.loads(os.environ["CHECKS_JSON"]); runs=[x for x in d.get("check_runs",[]) if x.get("name")==os.environ["CHECK_NAME"]]; latest=max(runs,key=lambda x:x.get("id",0),default=None); sys.exit(0 if latest and latest.get("status")=="completed" and latest.get("conclusion")=="success" else 1)' 2>/dev/null || refuse_pull "required check '$name' is missing, pending, or unsuccessful"
  done < <(printf '%s\n' "$required" | tr '|' '\n')
}

verify_pull_commit() {
  local requested="$1" resolved
  [[ "$requested" =~ ^[0-9a-f]{7,40}$ ]] || refuse_pull "commit must be a lowercase hexadecimal SHA"
  git -C "$server_checkout" fetch --force --no-tags origin +refs/heads/master:refs/remotes/origin/master >&2 || refuse_pull "could not fetch origin/master"
  resolved="$(git -C "$server_checkout" rev-parse --verify "$requested^{commit}" 2>/dev/null || true)"
  if [[ -z "$resolved" ]]; then
    GIT_TERMINAL_PROMPT=0 git -C "$server_checkout" fetch --no-tags origin "$requested" >&2 || refuse_pull "unknown commit $requested"
    resolved="$(git -C "$server_checkout" rev-parse --verify "$requested^{commit}" 2>/dev/null)" || refuse_pull "unknown commit $requested"
  fi
  git -C "$server_checkout" merge-base --is-ancestor "$resolved" origin/master || refuse_pull "commit $resolved is not reachable from origin/master"
  verify_required_checks "$resolved"
  verified_commit="$resolved"
}

pull_deploy() {
  local requested="$1" full_commit short_commit input server_root lock_file app_root state_root origin_url
  server_root="${MAYOS_SERVER_ROOT:-/opt/mayos}"
  [[ "$server_root" =~ ^(/[A-Za-z0-9._-]+)+$ ]] || refuse_pull 'server root must be a simple absolute path'
  server_checkout="${MAYOS_SERVER_CHECKOUT:-$server_root/src}"
  server_inputs="${MAYOS_SERVER_INPUTS:-$server_root/inputs}"
  app_root="$server_root/app"
  state_root="${MAYOS_SERVER_STATE:-$server_root/state}"
  lock_file="${MAYOS_SERVER_LOCK:-$state_root/deploy.lock}"
  [[ "$server_checkout" == "$server_root/"* && "$server_inputs" == "$server_root/"* && "$state_root" == "$server_root/"* && "$lock_file" == "$server_root/"* ]] || refuse_pull 'checkout, inputs, state, and lock paths must stay under server root'
  [[ "$server_checkout" =~ ^(/[A-Za-z0-9._-]+)+$ && "$server_inputs" =~ ^(/[A-Za-z0-9._-]+)+$ && "$state_root" =~ ^(/[A-Za-z0-9._-]+)+$ && "$lock_file" =~ ^(/[A-Za-z0-9._-]+)+$ ]] || refuse_pull 'checkout, inputs, state, and lock paths must be simple absolute paths'
  mkdir -p "$state_root" "$(dirname "$server_checkout")"
  exec 9>"$lock_file"
  flock -n 9 || refuse_pull 'another deployment is running'
  if [[ ! -d "$server_checkout/.git" ]]; then
    GIT_TERMINAL_PROMPT=0 git clone --no-checkout "${MAYOS_PUBLIC_REPO_URL:-https://github.com/ahmedtvmer/MYOS.git}" "$server_checkout" >&2 || refuse_pull 'could not clone public repository'
  fi
  origin_url="$(git -C "$server_checkout" remote get-url origin 2>/dev/null)" || refuse_pull 'checkout has no origin remote'
  [[ "$origin_url" == "${MAYOS_PUBLIC_REPO_URL:-https://github.com/ahmedtvmer/MYOS.git}" ]] || refuse_pull 'origin must be the public repository URL'
  verify_pull_commit "$requested"
  full_commit="$verified_commit"
  git -C "$server_checkout" checkout --force --detach "$full_commit" >&2 || refuse_pull 'could not check out verified commit'
  [[ "$(git -C "$server_checkout" rev-parse HEAD)" == "$full_commit" && -z "$(git -C "$server_checkout" status --porcelain)" ]] || refuse_pull 'checkout is dirty or does not match verified commit'
  for input in processed_exercises.csv food_library.csv food_portions.csv; do
    [[ -f "$server_inputs/$input" ]] || refuse_pull "required server input missing: $server_inputs/$input"
    install -m 0644 -- "$server_inputs/$input" "$server_checkout/data/$input"
  done
  [[ "$(git -C "$server_checkout" rev-parse HEAD)" == "$full_commit" ]] || refuse_pull 'checkout changed before build'
  if git -C "$server_checkout" status --porcelain --untracked-files=all | awk '$2 !~ /^data\/(processed_exercises|food_library|food_portions)\.csv$/ { bad=1 } END { exit bad }'; then :; else refuse_pull 'checkout contains unexpected dirty or untracked files'; fi
  # The protected inputs are intentionally untracked and are excluded from Git operations.
  repo_root="$server_checkout"
  script_dir="$server_checkout/deploy"
  server_pull_mode=1
  mkdir -p "$app_root/deploy"
  export MAYOS_PULL_IMAGE_ENV="$app_root/deploy/.image.env"
  export MAYOS_SERVER_STATE="$state_root"
  ssh_target=''
  history_rows="$(read_history)"
  current_tag="$(running_tag)"
  short_commit="$(git -C "$server_checkout" rev-parse --short=12 "$full_commit")"
  local deploy_tag
  deploy_tag="$(choose_image_tag "$short_commit")"
  deploy_release "$full_commit" "$deploy_tag"
  printf 'Deployment result: ready (%s).\n' "$full_commit"
}

read_history() {
  remote_bash <<'REMOTE'
state_dir="${MAYOS_SERVER_STATE:-/opt/mayos/state}"
history="$state_dir/deploy-history.tsv"
[[ -d "$state_dir" && -w "$state_dir" ]] || {
  echo "/opt/mayos/state is missing or not writable; rerun deploy/setup_vps.sh. If its setup marker was lost after bootstrap SSH access was removed, use the provider's web console recovery steps in docs/SERVER_SETUP.md." >&2
  exit 1
}
if [[ -f "$history" ]]; then cat "$history"; fi
REMOTE
}

running_tag() {
  remote_bash <<'REMOTE'
container="$(sudo docker ps -aq --filter label=com.docker.compose.project=mayos --filter label=com.docker.compose.service=api | awk 'NR == 1 { print }')"
[[ -n "$container" ]] || exit 0
image="$(sudo docker inspect --format '{{.Config.Image}}' "$container")"
case "$image" in
  mayos-api:*) printf '%s\n' "${image#mayos-api:}" ;;
  *) echo "Unexpected running API image reference: $image" >&2; exit 1 ;;
esac
REMOTE
}

set_image_tag() {
  local tag="$1"
  remote_bash "$tag" <<'REMOTE'
tag="$1"
[[ "$tag" =~ $IMAGE_TAG_RE ]] || { echo "Invalid image tag" >&2; exit 2; }
printf 'MAYOS_IMAGE_TAG=%s\n' "$tag" > "${MAYOS_PULL_IMAGE_ENV:-/opt/mayos/app/deploy/.image.env}"
REMOTE
}

compose_up() {
  remote_bash <<'REMOTE'
"${compose[@]}" up -d --no-deps --no-build api
REMOTE
}

start_companion_services() {
  remote_bash <<'REMOTE'
"${compose[@]}" up -d --no-build cloudflared litestream
REMOTE
}

build_and_start() {
  local tag="$1"
  remote_bash "$tag" <<'REMOTE'
tag="$1"
[[ "$tag" =~ $IMAGE_TAG_RE ]] || { echo "Invalid image tag" >&2; exit 2; }
"${compose[@]}" build api
"${compose[@]}" up -d --no-deps --no-build api
REMOTE
}

schema_version() {
  local tag="$1"
  remote_bash "$tag" <<'REMOTE'
tag="$1"
[[ "$tag" =~ $IMAGE_TAG_RE ]] || { echo "Invalid image tag" >&2; exit 2; }
sudo docker run --rm --network none --entrypoint python "mayos-api:$tag" -c \
  'import ast, pathlib; tree = ast.parse(pathlib.Path("/app/database/migration_manager.py").read_text()); assignment = next(node for node in tree.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "CURRENT_LEDGER_SCHEMA_VERSION"); version = assignment.value.value; assert type(version) is int and version >= 0; print(version)'
REMOTE
}

check_readiness() {
  remote_bash <<'REMOTE'
last_output="API readiness check did not run"
deadline=$((SECONDS + 180))
while (( SECONDS < deadline )); do
  remaining=$((deadline - SECONDS))
  request_timeout=4
  if (( remaining < request_timeout )); then request_timeout=$remaining; fi
  if (( request_timeout > 0 )) && last_output="$(timeout "${request_timeout}s" "${compose[@]}" exec -T api \
    curl -fsS --max-time "$request_timeout" http://localhost:8000/readyz 2>&1)"; then
    printf '%s\n' "$last_output"
    exit 0
  fi
  if (( SECONDS < deadline )); then sleep 1; fi
done
printf 'API did not become ready within 3 minutes. Last response: %s\n' "$last_output" >&2
exit 1
REMOTE
}

ensure_running_history() {
  local tag="$1"
  remote_bash "$tag" <<'REMOTE'
tag="$1"
[[ "$tag" =~ $IMAGE_TAG_RE ]] || { echo "Invalid current image tag" >&2; exit 2; }
history="${MAYOS_SERVER_STATE:-/opt/mayos/state}/deploy-history.tsv"
if [[ -f "$history" ]] && awk -F '\t' -v tag="$tag" '$2 == tag { found = 1 } END { exit !found }' "$history"; then
  exit 0
fi
temporary="$(mktemp "${MAYOS_SERVER_STATE:-/opt/mayos/state}/deploy-history.XXXXXX")"
{
  printf '%s\t%s\n' "$tag" "$tag"
  if [[ -f "$history" ]]; then
    awk -F '\t' -v tag="$tag" '$2 != tag && ++kept <= 2' "$history"
  fi
} > "$temporary"
mv "$temporary" "$history"
REMOTE
  if ! awk -F '\t' -v tag="$tag" '$2 == tag { found = 1 } END { exit !found }' <<< "$history_rows"; then
    history_rows="$tag"$'\t'"$tag"$'\n'"$history_rows"
  fi
}

remember_image() {
  local commit_ref="$1"
  local tag="$2"
  local previous_tag="${3:-}"
  remote_bash "$commit_ref" "$tag" "$previous_tag" <<'REMOTE'
commit_ref="$1"
tag="$2"
previous_tag="$3"
[[ "$commit_ref" =~ $IMAGE_TAG_RE && "$tag" =~ $IMAGE_TAG_RE && ( -z "$previous_tag" || "$previous_tag" =~ $IMAGE_TAG_RE ) ]] || {
  echo "Invalid image history record" >&2
  exit 2
}
history="${MAYOS_SERVER_STATE:-/opt/mayos/state}/deploy-history.tsv"
temporary="$(mktemp "${MAYOS_SERVER_STATE:-/opt/mayos/state}/deploy-history.XXXXXX")"
{
  printf '%s\t%s\n' "$commit_ref" "$tag"
  if [[ -f "$history" ]]; then
    awk -F '\t' -v commit="$commit_ref" -v tag="$tag" -v previous="$previous_tag" '
      BEGIN { kept = 1 }
      ($1 == commit || $2 == tag) { next }
      previous != "" && $2 == previous && kept < 3 { print; kept++; next }
      { rows[++count] = $0 }
      END {
        for (i = 1; i <= count && kept < 3; i++) {
          split(rows[i], fields, "\t")
          if (fields[2] != tag && (previous == "" || fields[2] != previous)) {
            print rows[i]
            kept++
          }
        }
      }' "$history"
  fi
} > "$temporary"
mv "$temporary" "$history"
REMOTE
}

prune_images() {
  local previous_tag="${1:-}"
  remote_bash "$previous_tag" <<'REMOTE'
previous_tag="$1"
history="${MAYOS_SERVER_STATE:-/opt/mayos/state}/deploy-history.tsv"
running_container="$(sudo docker ps -aq --filter label=com.docker.compose.project=mayos --filter label=com.docker.compose.service=api | awk 'NR == 1 { print }')"
running_image=""
if [[ -n "$running_container" ]]; then
  running_image="$(sudo docker inspect --format '{{.Config.Image}}' "$running_container")"
fi
while IFS= read -r image; do
  [[ "$image" == mayos-api:* ]] || continue
  [[ "$image" == "$running_image" || "$image" == "mayos-api:$previous_tag" ]] && continue
  tag="${image#mayos-api:}"
  [[ "$tag" =~ $IMAGE_TAG_RE ]] || continue
  if [[ -f "$history" ]] && awk -F '\t' -v tag="$tag" '$2 == tag { found = 1 } END { exit !found }' "$history"; then
    continue
  fi
  sudo docker image rm "$image" >/dev/null || printf 'Could not prune image %s\n' "$image" >&2
done < <(sudo docker image ls --format '{{.Repository}}:{{.Tag}}' mayos-api)
REMOTE
}

prune_build_cache_and_report_disk() {
  remote_bash <<'REMOTE'
sudo docker builder prune -f --filter until=168h
available_bytes="$(df -B1 --output=avail / | awk 'NR == 2 { print $1 }')"
[[ "$available_bytes" =~ ^[0-9]+$ ]] || {
  echo "could not read free space for /" >&2
  exit 1
}
df -h /
if (( available_bytes < 5000000000 )); then
  printf 'Warning: less than 5 GB is free on /.\n' >&2
fi
REMOTE
}

upload_build_input() {
  [[ "${server_pull_mode:-0}" == 1 ]] && return 0
  rsync -az --delete --delete-excluded -e ssh \
    --exclude='/.git/' --exclude='/.venv/' --exclude='/venv/' \
    --exclude='/mobile/' --exclude='/models/' --exclude='/node_modules/' \
    --exclude='/db/' --exclude='/logs/' --exclude='/.env' --exclude='/.env.*' \
    --exclude='/.claude/' --exclude='/.agents/' --exclude='/.pytest_cwd/' \
    --exclude='/.ruff_cache/' --exclude='/.pytest_cache/' --exclude='/.gitignore' \
    --exclude='/.vscode/' --exclude='/.idea/' --exclude='/.cache/' \
    --exclude='/.mypy_cache/' --exclude='/.tox/' --exclude='/__pycache__/' \
    --exclude='*.pyc' --exclude='*.pyo' --exclude='*.pyd' \
    --exclude='*.pem' --exclude='*.key' --exclude='*.p12' --exclude='*.jks' --exclude='*.keystore' \
    --filter='+ /data/' --filter='+ /data/processed_exercises.csv' \
    --filter='+ /data/exercise_curation.csv' \
    --filter='+ /data/food_library.csv' --filter='+ /data/food_portions.csv' \
    --filter='+ /data/food_curation.csv' --filter='+ /data/food_recipes.csv' --filter='- /data/***' \
    "$repo_root/" "$ssh_target:/opt/mayos/app/"
}

resolve_history_commit() {
  local requested="$1"
  local commit_ref
  local tag
  local matches=0
  local match_commit_ref
  local match_tag
  while IFS=$'\t' read -r commit_ref tag; do
    [[ "$commit_ref" =~ $IMAGE_TAG_RE && "$tag" =~ $IMAGE_TAG_RE ]] || continue
    if [[ "$commit_ref" == "$requested" || "$commit_ref" == "$requested"* || "$tag" == "$requested" ]]; then
      match_commit_ref="$commit_ref"
      match_tag="$tag"
      ((matches += 1))
    fi
  done <<< "$history_rows"
  [[ "$matches" -eq 1 ]] || return 1
  printf '%s\t%s' "$match_commit_ref" "$match_tag"
}

show_status() {
  printf 'Current API image: %s\n' "${current_tag:-none}"
  printf 'Kept image tags (newest first):\n'
  if [[ -z "$history_rows" ]]; then
    printf '  none\n'
  else
    while IFS=$'\t' read -r commit_ref tag; do
      [[ "$commit_ref" =~ $IMAGE_TAG_RE && "$tag" =~ $IMAGE_TAG_RE ]] || continue
      printf '  %s (%s)\n' "$tag" "$commit_ref"
    done <<< "$history_rows"
  fi
  if [[ -n "$current_tag" ]]; then
    check_readiness
  else
    printf 'API is not running; /readyz is unavailable.\n'
    return 1
  fi
}

image_tag_exists() {
  local candidate="$1"
  [[ "$candidate" =~ $IMAGE_TAG_RE ]] || return 1
  if [[ "${server_pull_mode:-0}" == 1 ]]; then
    sudo docker image inspect "mayos-api:$candidate" >/dev/null 2>&1
    return
  fi
  # shellcheck disable=SC2029 # the validated tag is meant to expand locally
  ssh "$ssh_target" sudo docker image inspect "mayos-api:$candidate" >/dev/null 2>&1
}

choose_image_tag() {
  local short_commit="$1"
  if [[ "$current_tag" == "$short_commit" ]] || image_tag_exists "$short_commit"; then
    timestamped_image_tag "$short_commit"
  else
    printf '%s' "$short_commit"
  fi
}

timestamped_image_tag() {
  local short_commit="$1"
  local attempt
  local candidate
  for ((attempt = 0; attempt < 10; attempt++)); do
    candidate="$short_commit-$(date -u +%Y%m%d%H%M%S)-$RANDOM"
    if ! image_tag_exists "$candidate"; then printf '%s' "$candidate"; return 0; fi
  done
  die "could not choose a unique image tag for commit $short_commit"
}

restore_previous_after_failure() {
  local new_tag="$1"
  local new_schema
  local old_schema
  if [[ -z "$current_tag" ]]; then
    die "new API failed readiness and there is no previous image to restore; image $new_tag is kept for recovery"
  fi
  image_tag_exists "$current_tag" ||
    die "new API failed readiness and previous image mayos-api:$current_tag is missing; automatic restore is unsafe"
  new_schema="$(schema_version "$new_tag" 2>/dev/null || true)"
  old_schema="$(schema_version "$current_tag" 2>/dev/null || true)"
  if ! python3 "$script_dir/rollback_guard.py" "$new_schema" "$old_schema"; then
    die "new API failed readiness and rollback was refused: new schema $new_schema is higher than previous schema $old_schema, or a schema version was missing/invalid. The new image remains running because ledgers may have migrated."
  fi
  printf 'Readiness failed; restoring previous image %s (schema %s) from new image schema %s.\n' "$current_tag" "$old_schema" "$new_schema" >&2
  set_image_tag "$current_tag"
  compose_up
  if check_readiness; then
    printf 'Automatic rollback to %s is ready.\n' "$current_tag" >&2
    printf 'Deployment result: rolled back (%s).\n' "$current_tag"
    die "deployment failed readiness; previous image $current_tag was restored"
  fi
  die "automatic rollback to $current_tag did not become ready; inspect the API logs"
}

deploy_release() {
  local full_commit="$1"
  local tag="$2"
  local previous_tag="$current_tag"
  if [[ -n "$previous_tag" ]]; then ensure_running_history "$previous_tag"; fi
  printf 'Deploying commit %s (image tag %s).\n' "$full_commit" "$tag"
  upload_build_input
  set_image_tag "$tag"
  build_and_start "$tag"
  if check_readiness; then
    start_companion_services
    remember_image "$full_commit" "$tag" "$previous_tag"
    prune_images "$previous_tag"
    prune_build_cache_and_report_disk
    printf 'Deployment %s is ready.\n' "$tag"
    return 0
  fi
  restore_previous_after_failure "$tag"
}

rollback_release() {
  local requested="$1"
  local resolved_commit
  local target_schema
  local current_schema
  local previous_tag
  local rollback_commit_ref
  local rollback_tag
  [[ "$requested" =~ ^[0-9a-f]{7,64}$ ]] || die "commit must be a lowercase hexadecimal SHA prefix"
  resolved_commit="$(resolve_history_commit "$requested")" ||
    die "commit is not one of the last three kept images (or the prefix is ambiguous)"
  IFS=$'\t' read -r rollback_commit_ref rollback_tag <<< "$resolved_commit"
  current_tag="$(running_tag)"
  [[ -n "$current_tag" ]] || die "there is no running API image to compare against"
  previous_tag="$current_tag"
  ensure_running_history "$current_tag"
  image_tag_exists "$rollback_tag" || die "image mayos-api:$rollback_tag is not present on the server"
  current_schema="$(schema_version "$current_tag" 2>/dev/null || true)"
  target_schema="$(schema_version "$rollback_tag" 2>/dev/null || true)"
  python3 "$script_dir/rollback_guard.py" "$current_schema" "$target_schema" ||
    die "rollback to $rollback_tag refused by the ledger schema guard"
  printf 'Restarting image %s (%s), ledger schema %s.\n' "$rollback_tag" "$rollback_commit_ref" "$target_schema"
  set_image_tag "$rollback_tag"
  compose_up
  check_readiness || die "rollback image $rollback_tag did not become ready; inspect the API logs"
  remember_image "$rollback_commit_ref" "$rollback_tag" "$previous_tag"
  prune_images "$previous_tag"
  printf 'Rollback to %s is ready.\n' "$rollback_tag"
}

main() {
  local command_name="${1:-deploy}"
  case "$command_name" in
    deploy|status) [[ $# -le 1 ]] || { usage >&2; exit 2; } ;;
    rollback) [[ $# -eq 2 ]] || { usage >&2; exit 2; } ;;
    pull) [[ $# -eq 2 ]] || { usage >&2; exit 2; } ;;
    -h|--help|help) usage; return 0 ;;
    *) usage >&2; exit 2 ;;
  esac

  if [[ "$command_name" == pull ]]; then pull_deploy "$2"; return; fi
  repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run this script inside the MAYOS checkout"
  git_dir="$(git -C "$repo_root" rev-parse --path-format=absolute --git-dir)"
  common_dir="$(git -C "$repo_root" rev-parse --path-format=absolute --git-common-dir)"
  if [[ -f "$repo_root/.git" || "$git_dir" != "$common_dir" ]]; then
    die "refusing to deploy from a git worktree; run from the main checkout"
  fi

  ssh_host="$(resolve_host)"
  ssh_target="deploy@$ssh_host"
  if [[ "$command_name" != status ]]; then warn_if_dirty; fi
  history_rows="$(read_history)"
  current_tag="$(running_tag)"
  case "$command_name" in
    deploy)
      full_commit="$(git -C "$repo_root" rev-parse HEAD)"
      short_commit="$(git -C "$repo_root" rev-parse --short=12 HEAD)"
      deploy_release "$full_commit" "$(choose_image_tag "$short_commit")"
      ;;
    rollback) rollback_release "$2" ;;
    status) show_status ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ "${1:-}" == __selftest-paths ]]; then
    printf '%s\n' "$script_dir/rollback_guard.py"
    exit 0
  fi
  main "$@"
fi
