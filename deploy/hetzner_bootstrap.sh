#!/usr/bin/env bash
# Bootstrap an Ubuntu MAYOS host with Docker, a required data mount, and deploy access.
# Usage: run as root from setup_hetzner.sh with a volume ID and base64 public key.
set -euo pipefail

if [[ $# -ne 2 || "$EUID" -ne 0 ]]; then
  printf 'Run as root with volume ID and base64 SSH public key arguments.\n' >&2
  exit 2
fi

volume_id="$1"
owner_public_key="$(printf '%s' "$2" | base64 -d)"
mount_path=/mnt/mayos-data
volume_device="/dev/disk/by-id/scsi-0HC_Volume_${volume_id}"
export DEBIAN_FRONTEND=noninteractive

setup_docker_repository() {
  local ubuntu_suite
  local docker_arch

  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck source=/dev/null
  . /etc/os-release
  ubuntu_suite="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
  docker_arch="$(dpkg --print-architecture)"
  cat > /etc/apt/sources.list.d/docker.sources <<DOCKER_REPO
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $ubuntu_suite
Components: stable
Architectures: $docker_arch
Signed-By: /etc/apt/keyrings/docker.asc
DOCKER_REPO
}

install_docker() {
  apt-get update
  apt-get install -y ca-certificates curl sudo unattended-upgrades
  setup_docker_repository
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

enable_security_updates() {
  cat > /etc/apt/apt.conf.d/20auto-upgrades <<'AUTO_UPGRADES'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
AUTO_UPGRADES
  systemctl enable --now apt-daily.timer apt-daily-upgrade.timer
}

create_deploy_user() {
  if ! id deploy >/dev/null 2>&1; then
    useradd --user-group --create-home --shell /bin/bash deploy
  fi
  if [[ " $(id -nG deploy) " == *" docker "* ]]; then
    gpasswd --delete deploy docker
  fi
  install -d -o deploy -g deploy -m 0700 /home/deploy/.ssh
  touch /home/deploy/.ssh/authorized_keys
}

install_deploy_key() {
  grep -qxF "$owner_public_key" /home/deploy/.ssh/authorized_keys ||
    printf '%s\n' "$owner_public_key" >> /home/deploy/.ssh/authorized_keys
  chown deploy:deploy /home/deploy/.ssh/authorized_keys
  chmod 0600 /home/deploy/.ssh/authorized_keys
}

write_volume_fstab_entry() {
  local volume_uuid="$1"
  local previous_mount_path="$2"
  local fstab_tmp

  fstab_tmp="$(mktemp)"
  awk -v uuid="UUID=$volume_uuid" -v device="$volume_device" \
    -v target="$mount_path" -v previous_target="$previous_mount_path" \
    '$1 != uuid && $1 != device && $2 != target && $2 != previous_target { print }' \
    /etc/fstab > "$fstab_tmp"
  printf 'UUID=%s %s ext4 defaults,nofail,x-systemd.device-timeout=30s 0 2\n' \
    "$volume_uuid" "$mount_path" >> "$fstab_tmp"
  chmod 0644 "$fstab_tmp"
  mv "$fstab_tmp" /etc/fstab
}

mount_data_volume() {
  local volume_uuid
  local mounted_target
  local mounted_uuid

  for _ in {1..30}; do
    [[ -b "$volume_device" ]] && break
    sleep 2
  done
  [[ -b "$volume_device" ]] || { echo "volume device not found: $volume_device" >&2; exit 1; }
  volume_uuid="$(blkid -s UUID -o value "$volume_device")"
  [[ -n "$volume_uuid" ]] || { echo "volume has no filesystem UUID" >&2; exit 1; }
  install -d -o root -g root -m 0755 "$mount_path"
  mounted_target="$(findmnt -rn -S "$volume_device" -o TARGET || true)"
  if [[ -n "$mounted_target" && "$mounted_target" != "$mount_path" ]]; then
    umount "$mounted_target"
  fi
  mounted_uuid="$(findmnt -rn -o UUID --mountpoint "$mount_path" 2>/dev/null || true)"
  if [[ -n "$mounted_uuid" && "$mounted_uuid" != "$volume_uuid" ]]; then
    echo "$mount_path is mounted from an unexpected volume" >&2
    exit 1
  fi
  write_volume_fstab_entry "$volume_uuid" "$mounted_target"
  [[ -n "$mounted_uuid" ]] || mount "$mount_path"
  mounted_uuid="$(findmnt -rn -o UUID --mountpoint "$mount_path" 2>/dev/null || true)"
  [[ "$mounted_uuid" == "$volume_uuid" ]] || {
    echo "expected volume UUID $volume_uuid at $mount_path, found ${mounted_uuid:-nothing}" >&2
    exit 1
  }
  # Dockerfile.fly has no USER directive, so both containers run as root.
  install -d -o root -g root -m 0755 "$mount_path/data"
}

prepare_mayos_paths() {
  install -d -o root -g root -m 0755 /opt/mayos
  install -d -o deploy -g deploy -m 0755 /opt/mayos/app
  install -d -o deploy -g deploy -m 0755 /opt/mayos/state
  if [[ -L /opt/mayos/.env || ( -e /opt/mayos/.env && ! -f /opt/mayos/.env ) ]]; then
    echo "/opt/mayos/.env must be a regular file" >&2
    exit 1
  fi
  if [[ ! -e /opt/mayos/.env ]]; then
    install -o root -g root -m 0600 /dev/null /opt/mayos/.env
  else
    chown root:root /opt/mayos/.env
    chmod 0600 /opt/mayos/.env
  fi
}

configure_deploy_sudo() {
  local sudoers_tmp

  sudoers_tmp="$(mktemp /etc/sudoers.d/.mayos-deploy.XXXXXX)"
  printf '%s\n' 'deploy ALL=(root) NOPASSWD: /usr/bin/docker, /usr/bin/sudoedit /opt/mayos/.env' \
    > "$sudoers_tmp"
  chmod 0440 "$sudoers_tmp"
  if ! visudo -cf "$sudoers_tmp"; then
    rm -f "$sudoers_tmp"
    return 1
  fi
  mv "$sudoers_tmp" /etc/sudoers.d/mayos-deploy
}

install_docker
enable_security_updates
create_deploy_user
install_deploy_key
mount_data_volume
prepare_mayos_paths
configure_deploy_sudo
