#!/usr/bin/env bash
# Bootstrap an Ubuntu VPS with Docker, a local data directory, and deploy access.
# Usage: run as root with the owner's base64-encoded public SSH key.
set -euo pipefail

if [[ $# -ne 1 || "$EUID" -ne 0 ]]; then
  printf 'Run as root with one base64-encoded public SSH key argument.\n' >&2
  exit 2
fi

owner_public_key="$(printf '%s' "$1" | base64 -d | awk 'NF { print; exit }')"
[[ -n "$owner_public_key" ]] || { echo "owner SSH public key is empty" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

setup_docker_repository() {
  local ubuntu_suite
  local docker_arch

  # shellcheck source=/dev/null
  . /etc/os-release
  ubuntu_suite="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
  docker_arch="$(dpkg --print-architecture)"
  if ! curl -fsI --max-time 15 \
    "https://download.docker.com/linux/ubuntu/dists/$ubuntu_suite/Release" >/dev/null; then
    printf "Docker's Ubuntu apt repository has no Release file for '%s'; use Ubuntu 24.04 or another supported image.\n" \
      "$ubuntu_suite" >&2
    return 1
  fi
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  cat > /etc/apt/sources.list.d/docker.sources <<DOCKER_REPO
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $ubuntu_suite
Components: stable
Architectures: $docker_arch
Signed-By: /etc/apt/keyrings/docker.asc
DOCKER_REPO
}

configure_host_firewall() {
  local ssh_port

  ssh_port="$(sshd -T | awk '$1 == "port" { print $2; exit }')"
  ssh_port="${ssh_port:-22}"
  [[ "$ssh_port" =~ ^[0-9]{1,5}$ ]] || {
    echo "could not determine a valid SSH port from sshd -T" >&2
    return 1
  }
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow "$ssh_port/tcp"
  ufw --force enable
}

install_docker() {
  apt-get update
  apt-get install -y ca-certificates curl sudo unattended-upgrades ufw
  setup_docker_repository
  configure_host_firewall
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

prepare_mayos_paths() {
  # Dockerfile.fly has no USER directive, so both containers run as root.
  install -d -o root -g root -m 0755 /mnt/mayos-data/data
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
prepare_mayos_paths
configure_deploy_sudo
install -o root -g root -m 0644 /dev/null /opt/mayos/state/.bootstrap-complete
