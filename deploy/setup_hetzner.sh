#!/usr/bin/env bash
# Provision the MAYOS Hetzner server, SSH key, firewall, and data volume.
# Usage: bash deploy/setup_hetzner.sh; configure overrides through environment variables.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HCLOUD_ENV_FILE="${HCLOUD_ENV_FILE:-$REPO_ROOT/.env}"
HCLOUD_LOCATION="${HCLOUD_LOCATION:-fsn1}"
HCLOUD_SERVER_TYPE="${HCLOUD_SERVER_TYPE:-cx23}"
HCLOUD_IMAGE="${HCLOUD_IMAGE:-ubuntu-24.04}"
HCLOUD_VOLUME_SIZE="${HCLOUD_VOLUME_SIZE:-10}"
HCLOUD_SERVER_NAME="${HCLOUD_SERVER_NAME:-mayos-api}"
HCLOUD_VOLUME_NAME="${HCLOUD_VOLUME_NAME:-mayos-data}"
HCLOUD_FIREWALL_NAME="${HCLOUD_FIREWALL_NAME:-mayos-fw}"
HCLOUD_SSH_KEY_NAME="${HCLOUD_SSH_KEY_NAME:-mayos-deploy-key}"
SSH_PUBLIC_KEY_PATH="${SSH_PUBLIC_KEY_PATH:-$HOME/.ssh/id_ed25519.pub}"
SSH_PRIVATE_KEY_PATH="${SSH_PRIVATE_KEY_PATH:-${SSH_PUBLIC_KEY_PATH%.pub}}"

die() {
  printf 'setup_hetzner: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

load_hcloud_token() {
  local env_line

  if [[ -z "${HCLOUD_TOKEN:-}" && -f "$HCLOUD_ENV_FILE" ]]; then
    while IFS= read -r env_line || [[ -n "$env_line" ]]; do
      env_line="${env_line%$'\r'}"
      case "$env_line" in
        HCLOUD_TOKEN=*)
          HCLOUD_TOKEN="${env_line#HCLOUD_TOKEN=}"
          break
          ;;
      esac
    done < "$HCLOUD_ENV_FILE"
  fi

  [[ -n "${HCLOUD_TOKEN:-}" ]] || die "set HCLOUD_TOKEN in the environment or $HCLOUD_ENV_FILE"
  export HCLOUD_TOKEN
}

resource_id_by_name() {
  local resource_kind="$1"
  local resource_name="$2"

  # shellcheck disable=SC2016
  hcloud "$resource_kind" list --output json |
    jq -r --arg resource_name "$resource_name" \
      'first(.[] | select(.name == $resource_name) | .id) // empty'
}

ensure_ssh_key() {
  local existing_key_id
  local expected_public_key
  local stored_public_key

  existing_key_id="$(resource_id_by_name ssh-key "$HCLOUD_SSH_KEY_NAME")"
  if [[ -z "$existing_key_id" ]]; then
    hcloud ssh-key create --name "$HCLOUD_SSH_KEY_NAME" \
      --public-key-from-file "$SSH_PUBLIC_KEY_PATH" >/dev/null
    return
  fi

  expected_public_key="$(awk '{print $1 " " $2}' "$SSH_PUBLIC_KEY_PATH")"
  stored_public_key="$(hcloud ssh-key describe "$HCLOUD_SSH_KEY_NAME" --output json |
    jq -r '.public_key | split(" ")[:2] | join(" ")')"
  [[ "$expected_public_key" == "$stored_public_key" ]] ||
    die "Hetzner SSH key '$HCLOUD_SSH_KEY_NAME' does not match $SSH_PUBLIC_KEY_PATH"
}

add_ssh_firewall_rule() {
  hcloud firewall add-rule "$HCLOUD_FIREWALL_NAME" --direction in \
    --protocol tcp --port 22 --source-ips 0.0.0.0/0 --source-ips ::/0 \
    --description "SSH only" >/dev/null
}

firewall_inbound_is_ssh_only() {
  jq -e '
      [.[]] as $incoming
      | ($incoming | length) == 1
      and $incoming[0].protocol == "tcp"
      and $incoming[0].port == "22"
      and ($incoming[0].source_ips | index("0.0.0.0/0") != null)
      and ($incoming[0].source_ips | index("::/0") != null)
    ' <<<"$1" >/dev/null
}

ensure_firewall() {
  local existing_firewall_id
  local inbound_rules

  existing_firewall_id="$(resource_id_by_name firewall "$HCLOUD_FIREWALL_NAME")"
  if [[ -z "$existing_firewall_id" ]]; then
    hcloud firewall create --name "$HCLOUD_FIREWALL_NAME" >/dev/null
    add_ssh_firewall_rule
    return
  fi

  inbound_rules="$(hcloud firewall describe "$HCLOUD_FIREWALL_NAME" --output json |
    jq '[.rules[] | select(.direction == "in")]')"
  if [[ "$inbound_rules" == "[]" ]]; then
    add_ssh_firewall_rule
    return
  fi
  firewall_inbound_is_ssh_only "$inbound_rules" ||
    die "Hetzner firewall '$HCLOUD_FIREWALL_NAME' has unexpected inbound rules"
}

ensure_firewall_applied() {
  local firewall_id
  local server_json
  local applied_firewalls

  firewall_id="$(resource_id_by_name firewall "$HCLOUD_FIREWALL_NAME")"
  server_json="$(hcloud server describe "$HCLOUD_SERVER_NAME" --output json)"
  applied_firewalls="$(jq -c '[.public_net.firewalls[]?.id]' <<<"$server_json")"
  if [[ "$applied_firewalls" == "[]" ]]; then
    hcloud firewall apply-to-resource --type server --server "$HCLOUD_SERVER_NAME" \
      "$HCLOUD_FIREWALL_NAME" >/dev/null
    server_json="$(hcloud server describe "$HCLOUD_SERVER_NAME" --output json)"
    applied_firewalls="$(jq -c '[.public_net.firewalls[]?.id]' <<<"$server_json")"
  fi
  [[ "$applied_firewalls" == "[$firewall_id]" ]] ||
    die "server must have only the SSH firewall '$HCLOUD_FIREWALL_NAME' on its public interface"
}

verify_existing_volume() {
  local volume_json
  local volume_location
  local volume_size
  local volume_format

  volume_json="$(hcloud volume describe "$HCLOUD_VOLUME_NAME" --output json)"
  volume_location="$(jq -r '.location.name' <<<"$volume_json")"
  volume_size="$(jq -r '.size' <<<"$volume_json")"
  volume_format="$(jq -r '.format // empty' <<<"$volume_json")"
  [[ "$volume_location" == "$HCLOUD_LOCATION" ]] ||
    die "existing volume is in $volume_location, expected $HCLOUD_LOCATION"
  [[ "$volume_format" == "ext4" ]] || die "Hetzner volume must be formatted as ext4"
  (( volume_size >= HCLOUD_VOLUME_SIZE )) ||
    die "existing volume is smaller than requested size $HCLOUD_VOLUME_SIZE GB"
}

ensure_existing_server() {
  local server_json
  local server_type
  local server_location
  local server_image
  local server_status

  server_json="$(hcloud server describe "$HCLOUD_SERVER_NAME" --output json)"
  server_type="$(jq -r '.server_type.name' <<<"$server_json")"
  server_location="$(jq -r '.location.name' <<<"$server_json")"
  server_image="$(jq -r '.image.name // empty' <<<"$server_json")"
  server_status="$(jq -r '.status' <<<"$server_json")"
  [[ "$server_type" == "$HCLOUD_SERVER_TYPE" ]] || die "existing server has type $server_type"
  [[ "$server_location" == "$HCLOUD_LOCATION" ]] || die "existing server is in $server_location"
  [[ "$server_image" == "$HCLOUD_IMAGE" ]] || die "existing server image is $server_image, expected $HCLOUD_IMAGE"
  if [[ "$server_status" == "off" ]]; then
    hcloud server poweron "$HCLOUD_SERVER_NAME" >/dev/null
  fi
}

ensure_server() {
  local server_id

  server_id="$(resource_id_by_name server "$HCLOUD_SERVER_NAME")"
  if [[ -z "$server_id" ]]; then
    hcloud server create --name "$HCLOUD_SERVER_NAME" \
      --type "$HCLOUD_SERVER_TYPE" --image "$HCLOUD_IMAGE" \
      --location "$HCLOUD_LOCATION" --ssh-key "$HCLOUD_SSH_KEY_NAME" \
      --firewall "$HCLOUD_FIREWALL_NAME" >/dev/null
    return
  fi
  ensure_existing_server
}

attach_volume_to_server() {
  local attached_server_id
  local server_id

  server_id="$(hcloud server describe "$HCLOUD_SERVER_NAME" --output json | jq -r '.id')"
  attached_server_id="$(hcloud volume describe "$HCLOUD_VOLUME_NAME" --output json |
    jq -r '.server // empty')"
  if [[ -z "$attached_server_id" ]]; then
    hcloud volume attach --automount --server "$HCLOUD_SERVER_NAME" \
      "$HCLOUD_VOLUME_NAME" >/dev/null
  elif [[ "$attached_server_id" != "$server_id" ]]; then
    die "Hetzner volume '$HCLOUD_VOLUME_NAME' is attached to a different server"
  fi
}

ensure_volume() {
  local volume_id

  volume_id="$(resource_id_by_name volume "$HCLOUD_VOLUME_NAME")"
  if [[ -z "$volume_id" ]]; then
    hcloud volume create --name "$HCLOUD_VOLUME_NAME" --size "$HCLOUD_VOLUME_SIZE" \
      --location "$HCLOUD_LOCATION" --format ext4 >/dev/null
  fi

  verify_existing_volume
  attach_volume_to_server
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
  local server_ip="$2"

  ssh "${ssh_options[@]}" "$ssh_user@$server_ip" true >/dev/null 2>&1
}

wait_for_ssh() {
  local ssh_user="$1"
  local server_ip="$2"

  for _ in {1..12}; do
    can_ssh_as "$ssh_user" "$server_ip" && return 0
    sleep 5
  done
  return 1
}

bootstrap_server() {
  local server_ip="$1"
  local volume_id="$2"
  local owner_public_key_base64

  owner_public_key_base64="$(base64 < "$SSH_PUBLIC_KEY_PATH" | tr -d '\n')"
  ssh "${ssh_options[@]}" "root@$server_ip" bash -s -- \
    "$volume_id" "$owner_public_key_base64" < "$REPO_ROOT/deploy/hetzner_bootstrap.sh"
}

harden_ssh() {
  local server_ip="$1"

  wait_for_ssh deploy "$server_ip" || die "deploy SSH login did not work; root SSH remains enabled"
  ssh "${ssh_options[@]}" "root@$server_ip" bash -s <<'REMOTE_SSHD'
set -euo pipefail
cat > /etc/ssh/sshd_config.d/00-mayos-hardening.conf <<'SSHD_CONFIG'
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
SSHD_CONFIG
sshd -t
systemctl reload ssh
REMOTE_SSHD
  wait_for_ssh deploy "$server_ip" || die "deploy SSH login failed after SSH hardening"
}

validate_local_setup() {
  require_command hcloud
  require_command jq
  require_command ssh
  require_command awk
  require_command base64
  require_command tr
  case "$HCLOUD_LOCATION" in
    fsn1|nbg1) ;;
    *) die "HCLOUD_LOCATION must be fsn1 or nbg1" ;;
  esac
  [[ -f "$SSH_PUBLIC_KEY_PATH" ]] || die "SSH public key not found: $SSH_PUBLIC_KEY_PATH"
  [[ -f "$SSH_PRIVATE_KEY_PATH" ]] || die "SSH private key not found: $SSH_PRIVATE_KEY_PATH"
  [[ "$HCLOUD_VOLUME_SIZE" =~ ^[0-9]+$ ]] || die "HCLOUD_VOLUME_SIZE must be an integer number of GB"
  (( HCLOUD_VOLUME_SIZE >= 10 )) || die "Hetzner volumes must be at least 10 GB"
}

provision_cloud_resources() {
  ensure_ssh_key
  ensure_firewall
  ensure_server
  ensure_firewall_applied
  ensure_volume
}

configure_server_access() {
  local server_json
  local server_ip
  local volume_id

  server_json="$(hcloud server describe "$HCLOUD_SERVER_NAME" --output json)"
  server_ip="$(jq -er '.public_net.ipv4.ip' <<<"$server_json")"
  volume_id="$(resource_id_by_name volume "$HCLOUD_VOLUME_NAME")"
  [[ -n "$volume_id" ]] || die "Hetzner volume '$HCLOUD_VOLUME_NAME' was not created"
  if can_ssh_as deploy "$server_ip"; then
    printf 'Deploy SSH is already configured; skipping the root bootstrap.\n'
  else
    wait_for_ssh root "$server_ip" ||
      die "cannot SSH as root or deploy to $server_ip; check the owner's SSH key and server access"
    bootstrap_server "$server_ip" "$volume_id"
    harden_ssh "$server_ip"
  fi
  ssh "${ssh_options[@]}" "deploy@$server_ip" sudo docker compose version >/dev/null
  printf 'Hetzner setup is ready. Server: %s (%s)\n' "$HCLOUD_SERVER_NAME" "$server_ip"
  printf 'Volume: %s mounted at /mnt/mayos-data (application data: /mnt/mayos-data/data)\n' \
    "$HCLOUD_VOLUME_NAME"
  printf 'Complete the owner checklist in docs/HETZNER_SETUP.md before deploying.\n'
}

main() {
  [[ $# -eq 0 ]] || die "configure setup with environment variables; no positional arguments are accepted"
  validate_local_setup
  load_hcloud_token
  provision_cloud_resources
  configure_server_access
}

main "$@"
