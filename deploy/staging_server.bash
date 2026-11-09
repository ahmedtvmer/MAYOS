#!/usr/bin/env bash
# Sent over SSH by deploy_server.sh; also installed for the systemd TTL check.
set -euo pipefail
# Command substitutions must fail too, so a bad TTL can never stop staging.
shopt -s inherit_errexit

staging_state=/opt/mayos/state/staging

staging_require_setup() {
  [[ -f /opt/mayos/staging.env ]] || {
    echo 'Staging refused: /opt/mayos/staging.env is missing; complete the one-time staging setup.' >&2
    exit 1
  }
  [[ -d /mnt/mayos-data/staging ]] || {
    echo 'Staging refused: /mnt/mayos-data/staging is missing; create the staging data folder first.' >&2
    exit 1
  }
}

staging_lock() {
  mkdir -p "$staging_state"
  exec 9>"$staging_state/deploy.lock"
  flock -n 9 || { echo 'Staging refused: another staging operation is running.' >&2; exit 1; }
}

staging_upload_path() {
  [[ "$1" =~ ^/opt/mayos/state/staging/upload\.[A-Za-z0-9]+$ ]] || {
    echo 'Staging refused: invalid upload path.' >&2
    exit 1
  }
}

staging_container() {
  sudo docker ps -aq --filter label=com.docker.compose.project=mayos-staging \
    --filter label=com.docker.compose.service=api | awk 'NR == 1 { print }'
}

staging_stop() {
  local container
  container="$(staging_container)"
  if [[ -n "$container" ]]; then
    sudo docker stop --time 60 "$container" >/dev/null
    sudo docker rm "$container" >/dev/null
  fi
  printf 'Staging is off.\n'
}

staging_ttl_seconds() {
  local hours="$1"
  [[ "$hours" =~ ^[1-9][0-9]{0,3}$ ]] || {
    echo 'Staging refused: MAYOS_STAGING_TTL_HOURS must be a positive whole number (1-9999).' >&2
    return 1
  }
  printf '%s\n' "$((10#$hours * 3600))"
}

staging_deadline_epoch() {
  local container="$1" started_at="$2" started_epoch ttl_hours ttl_seconds
  started_epoch="$(date -d "$started_at" +%s)"
  ttl_hours="$(sudo docker inspect --format '{{index .Config.Labels "online.mayos.staging.ttl-hours"}}' "$container")"
  ttl_seconds="$(staging_ttl_seconds "$ttl_hours")"
  printf '%s\n' "$((started_epoch + ttl_seconds))"
}

staging_status() {
  local container started_at stop_epoch
  container="$(staging_container)"
  if [[ -z "$container" ]]; then printf 'Staging is off.\n'; return; fi
  printf 'Staging running: %s\n' "$(sudo docker inspect --format '{{.State.Running}}' "$container")"
  printf 'Commit: %s\n' "$(sudo docker inspect --format '{{index .Config.Labels "online.mayos.staging.commit"}}' "$container")"
  started_at="$(sudo docker inspect --format '{{.State.StartedAt}}' "$container")"
  stop_epoch="$(staging_deadline_epoch "$container" "$started_at")"
  printf 'Started: %s\nAuto-stops: %s (next 15-minute timer check)\n' \
    "$started_at" "$(date -u -d "@$stop_epoch" +%Y-%m-%dT%H:%M:%SZ)"
}

staging_autostop() {
  local container started_at stop_epoch now
  container="$(staging_container)"
  [[ -n "$container" ]] || return 0
  [[ "$(sudo docker inspect --format '{{.State.Running}}' "$container")" == true ]] || return 0
  started_at="$(sudo docker inspect --format '{{.State.StartedAt}}' "$container")"
  stop_epoch="$(staging_deadline_epoch "$container" "$started_at")"
  now="$(date +%s)"
  # The boundary is inclusive: the first check at or after expiry stops staging.
  if (( now >= stop_epoch )); then
    printf 'Staging TTL expired (%s); stopping.\n' "$started_at"
    staging_stop
  fi
}

staging_wait_ready() {
  local last_output='API readiness check did not run' deadline=$((SECONDS + 180)) remaining request_timeout
  while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    request_timeout=4
    if (( remaining < request_timeout )); then request_timeout=$remaining; fi
    if (( request_timeout > 0 )) && last_output="$(timeout "${request_timeout}s" "${compose[@]}" exec -T api \
      curl -fsS --max-time "$request_timeout" http://localhost:8000/readyz 2>&1)"; then
      printf '%s\n' "$last_output"
      return 0
    fi
    if (( SECONDS < deadline )); then sleep 1; fi
  done
  printf 'Staging API did not become ready within 3 minutes. Last response: %s\n' "$last_output" >&2
  return 1
}

staging_build() (
  local tag="$1" commit="$2"
  # A separate bounded BuildKit daemon protects production during image builds too.
  trap 'sudo docker buildx rm mayos-staging-builder >/dev/null' EXIT
  sudo docker buildx create --name mayos-staging-builder --driver docker-container \
    --driver-opt memory=1536m,memory-swap=1536m >/dev/null
  sudo docker buildx build --builder mayos-staging-builder --load \
    --file "$staging_state/app/Dockerfile.fly" --build-arg "GIT_COMMIT=$commit" \
    --tag "mayos-api-staging:$tag" "$staging_state/app"
)

staging_prune_images() {
  local image tag
  while IFS= read -r image; do
    [[ "$image" == mayos-api-staging:* ]] || continue
    tag="${image#mayos-api-staging:}"
    if ! awk -F '\t' -v tag="$tag" '$2 == tag { found=1 } END { exit !found }' "$staging_state/history.tsv"; then
      sudo docker image rm "$image" >/dev/null || printf 'Could not prune staging image %s\n' "$image" >&2
    fi
  done < <(sudo docker image ls --format '{{.Repository}}:{{.Tag}}' mayos-api-staging)
}

staging_remember_image() {
  local commit="$1" tag="$2" temporary
  temporary="$(mktemp "$staging_state/history.XXXXXX")"
  {
    printf '%s\t%s\n' "$commit" "$tag"
    if [[ -f "$staging_state/history.tsv" ]]; then
      awk -F '\t' -v tag="$tag" '$2 != tag && ++kept <= 1' "$staging_state/history.tsv"
    fi
  } > "$temporary"
  mv "$temporary" "$staging_state/history.tsv"
}

staging_up() {
  local upload_dir="$1" tag="$2" commit="$3" ttl_hours input
  staging_upload_path "$upload_dir"
  [[ "$tag" =~ ^[0-9a-f]{7,64}-[0-9]{14}-[0-9]{1,5}$ && "$commit" =~ ^[0-9a-f]{40,64}$ ]] || {
    echo 'Staging refused: invalid commit or image tag.' >&2; exit 1;
  }
  staging_require_setup
  rm -rf -- "$staging_state/app"
  mv -- "$upload_dir" "$staging_state/app"
  mkdir -p "$staging_state/app/data"
  for input in processed_exercises.csv food_library.csv food_portions.csv; do
    [[ -f "$staging_state/app/data/$input" ]] && continue
    [[ -f "/opt/mayos/inputs/$input" ]] || {
      printf 'Staging refused: required build input %s is missing from the checkout and /opt/mayos/inputs/%s.\n' "$input" "$input" >&2
      exit 1
    }
    install -m 0644 -- "/opt/mayos/inputs/$input" "$staging_state/app/data/$input"
  done
  printf 'MAYOS_STAGING_IMAGE_TAG=%s\nMAYOS_STAGING_COMMIT=%s\n' "$tag" "$commit" > "$staging_state/image.env"
  local -a compose=(sudo docker compose -f "$staging_state/app/deploy/compose.staging.yaml"
    --env-file /opt/mayos/staging.env --env-file "$staging_state/image.env" -p mayos-staging)
  ttl_hours="$("${compose[@]}" config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["api"]["labels"]["online.mayos.staging.ttl-hours"])')"
  staging_ttl_seconds "$ttl_hours" >/dev/null
  staging_build "$tag" "$commit"
  "${compose[@]}" up -d --no-deps --no-build --force-recreate api
  staging_remember_image "$commit" "$tag"
  staging_prune_images
  staging_wait_ready
  staging_status
}

staging_main() {
  case "${1:-}" in
    prepare)
      staging_require_setup
      mkdir -p "$staging_state"
      mktemp -d "$staging_state/upload.XXXXXXXX"
      ;;
    cleanup) staging_upload_path "$2"; rm -rf -- "$2" ;;
    up) staging_lock; staging_up "$2" "$3" "$4" ;;
    down) staging_lock; staging_stop ;;
    status) staging_lock; staging_status ;;
    autostop) staging_lock; staging_autostop ;;
    *) echo 'Usage: staging_server.bash prepare|cleanup|up|down|status|autostop' >&2; exit 2 ;;
  esac
}

if [[ "${BASH_SOURCE[0]:-}" == "$0" ]]; then staging_main "$@"; fi
