#!/usr/bin/env bash
# Prepare a MAYOS VPS over SSH after it has been created in the provider console.
# Usage: deploy/setup_vps.sh [server-ip].
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
MAYOS_BOOTSTRAP_USER="${MAYOS_BOOTSTRAP_USER:-ubuntu}"
SSH_PUBLIC_KEY_PATH="${SSH_PUBLIC_KEY_PATH:-$HOME/.ssh/id_ed25519.pub}"
SSH_PRIVATE_KEY_PATH="${SSH_PRIVATE_KEY_PATH:-${SSH_PUBLIC_KEY_PATH%.pub}}"

die() {
  printf 'setup_vps: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

resolve_server_address() {
  local env_line
  local configured_host="${MAYOS_DEPLOY_HOST:-}"

  [[ $# -le 1 ]] || die "usage: deploy/setup_vps.sh [server-ip]"
  if [[ $# -eq 1 ]]; then
    configured_host="$1"
  elif [[ -z "$configured_host" && -f "$repo_root/.env" ]]; then
    while IFS= read -r env_line || [[ -n "$env_line" ]]; do
      env_line="${env_line%$'\r'}"
      case "$env_line" in
        MAYOS_DEPLOY_HOST=*)
          configured_host="${env_line#MAYOS_DEPLOY_HOST=}"
          break
          ;;
      esac
    done < "$repo_root/.env"
  fi
  [[ "$configured_host" =~ ^[A-Za-z0-9._:-]+$ && "$configured_host" != -* ]] ||
    die "pass the server IP or set MAYOS_DEPLOY_HOST in the environment or checkout .env"
  printf '%s' "$configured_host"
}

validate_setup() {
  local server_address="$1"

  [[ "$MAYOS_BOOTSTRAP_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] ||
    die "MAYOS_BOOTSTRAP_USER must be a valid lowercase Linux username"
  [[ "$MAYOS_BOOTSTRAP_USER" != root && "$MAYOS_BOOTSTRAP_USER" != deploy ]] ||
    die "MAYOS_BOOTSTRAP_USER must be the image's non-root sudo user, not deploy"
  [[ "$server_address" =~ ^[A-Za-z0-9._:-]+$ && "$server_address" != -* ]] ||
    die "server address must contain only IP or hostname characters"
  require_command ssh
  require_command base64
  require_command tr
  [[ -f "$SSH_PUBLIC_KEY_PATH" ]] || die "SSH public key not found: $SSH_PUBLIC_KEY_PATH"
  [[ -f "$SSH_PRIVATE_KEY_PATH" ]] || die "SSH private key not found: $SSH_PRIVATE_KEY_PATH"
}

ssh_options=(
  -i "$SSH_PRIVATE_KEY_PATH"
  -o IdentitiesOnly=yes
  -o BatchMode=yes
  -o ConnectTimeout=5
  -o StrictHostKeyChecking=accept-new
)

can_ssh_as() {
  local ssh_user="$1"
  local server_address="$2"

  ssh "${ssh_options[@]}" "$ssh_user@$server_address" true >/dev/null 2>&1
}

wait_for_ssh() {
  local ssh_user="$1"
  local server_address="$2"

  for _ in {1..12}; do
    can_ssh_as "$ssh_user" "$server_address" && return 0
    sleep 5
  done
  return 1
}

check_setup_complete() {
  local server_address="$1"

  ssh "${ssh_options[@]}" "deploy@$server_address" bash -s <<'REMOTE_SETUP_CHECK'
[[ -r /opt/mayos/state/.setup-complete ]] || exit 3
sudo docker compose version >/dev/null || exit 4
REMOTE_SETUP_CHECK
}

verify_deploy_access() {
  local server_address="$1"

  ssh "${ssh_options[@]}" "deploy@$server_address" sudo docker compose version >/dev/null
}

bootstrap_server() {
  local server_address="$1"
  local owner_public_key_base64

  owner_public_key_base64="$(base64 < "$SSH_PUBLIC_KEY_PATH" | tr -d '\n')"
  ssh "${ssh_options[@]}" "$MAYOS_BOOTSTRAP_USER@$server_address" sudo bash -s -- \
    "$owner_public_key_base64" < "$script_dir/server_bootstrap.sh"
}

finalize_server_setup() {
  local server_address="$1"

  ssh "${ssh_options[@]}" "$MAYOS_BOOTSTRAP_USER@$server_address" sudo bash -s -- \
    "$MAYOS_BOOTSTRAP_USER" <<'FINAL_SETUP'
set -euo pipefail
bootstrap_user="$1"
state_dir=/opt/mayos/state
[[ -r "$state_dir/.bootstrap-complete" ]] || {
  echo "server bootstrap did not complete; refusing SSH hardening" >&2
  exit 1
}
setup_marker_tmp="$state_dir/.setup-complete.tmp"
install -o root -g root -m 0644 /dev/null "$setup_marker_tmp"
cat > /etc/ssh/sshd_config.d/00-mayos-hardening.conf <<'SSHD_CONFIG'
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
SSHD_CONFIG
sshd -t
systemctl reload ssh
user_home="$(getent passwd "$bootstrap_user" | cut -d: -f6)"
[[ -n "$user_home" ]] || { echo "bootstrap user's home directory was not found" >&2; exit 1; }
rm -f -- "$user_home/.ssh/authorized_keys"
mv -f -- "$setup_marker_tmp" "$state_dir/.setup-complete"
FINAL_SETUP
}

configure_server_access() {
  local server_address="$1"
  local setup_status=0

  if check_setup_complete "$server_address"; then
    printf 'Server setup marker and Docker Compose access are ready.\n'
    return 0
  else
    setup_status=$?
  fi
  [[ "$setup_status" -ne 4 ]] ||
    die "setup is marked complete but deploy cannot run sudo docker compose"

  wait_for_ssh "$MAYOS_BOOTSTRAP_USER" "$server_address" ||
    die "cannot SSH as $MAYOS_BOOTSTRAP_USER. If the setup marker or state directory was lost after setup, use the OVH console recovery steps in docs/SERVER_SETUP.md."
  bootstrap_server "$server_address"
  verify_deploy_access "$server_address" ||
    die "deploy SSH and sudo access did not work; SSH settings were not changed"
  finalize_server_setup "$server_address"
  verify_deploy_access "$server_address" ||
    die "deploy SSH or sudo access failed after hardening; use the OVH console to recover access"
}

main() {
  local server_address

  server_address="$(resolve_server_address "$@")"
  validate_setup "$server_address"
  configure_server_access "$server_address"
  printf 'VPS setup is ready: %s\n' "$server_address"
  printf 'Complete the owner checklist in docs/SERVER_SETUP.md before deploying.\n'
}

main "$@"
