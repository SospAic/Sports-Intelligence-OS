#!/usr/bin/env bash

# Installs Docker Engine from Docker's official repository when necessary, then
# delegates the project bootstrap to install-common.sh.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_DOCKER_INSTALL=0
COMMON_ARGS=()

while (($#)); do
  case "$1" in
    -h|--help)
      bash "${SCRIPT_DIR}/install-common.sh" --help
      echo "  --skip-docker-install   Require an existing Docker Engine and Compose v2"
      exit 0
      ;;
    --skip-docker-install)
      SKIP_DOCKER_INSTALL=1
      shift
      ;;
    *)
      COMMON_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ ! -r /etc/os-release ]]; then
  echo "Cannot identify this Linux distribution: /etc/os-release is unavailable." >&2
  exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release

SUDO=()
if ((EUID != 0)); then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Docker installation requires root privileges or sudo." >&2
    exit 1
  fi
  SUDO=(sudo)
fi

install_docker_apt() {
  local distribution="$1"
  local codename="${VERSION_CODENAME:-}"
  if [[ "${distribution}" == "ubuntu" && -n "${UBUNTU_CODENAME:-}" ]]; then
    codename="${UBUNTU_CODENAME}"
  fi
  if [[ -z "${codename}" ]]; then
    echo "Unable to determine the apt repository codename." >&2
    exit 1
  fi

  "${SUDO[@]}" apt-get update
  "${SUDO[@]}" apt-get install -y ca-certificates curl openssl
  "${SUDO[@]}" install -m 0755 -d /etc/apt/keyrings
  local key_file
  key_file="$(mktemp)"
  curl --fail --silent --show-error --location \
    "https://download.docker.com/linux/${distribution}/gpg" \
    --output "${key_file}"
  "${SUDO[@]}" install -m 0644 "${key_file}" \
    /etc/apt/keyrings/docker.asc
  rm -f "${key_file}"
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
    "$(dpkg --print-architecture)" "${distribution}" "${codename}" \
    | "${SUDO[@]}" tee /etc/apt/sources.list.d/docker.list >/dev/null
  "${SUDO[@]}" apt-get update
  "${SUDO[@]}" apt-get install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

install_docker_rpm() {
  local distribution="$1"
  local repository_distribution="${distribution}"
  "${SUDO[@]}" dnf -y install dnf-plugins-core curl openssl

  case "${distribution}" in
    fedora)
      if [[ ! -f /etc/yum.repos.d/docker-ce.repo ]]; then
        "${SUDO[@]}" dnf config-manager addrepo --from-repofile \
          https://download.docker.com/linux/fedora/docker-ce.repo
      fi
      ;;
    rhel)
      if [[ ! -f /etc/yum.repos.d/docker-ce.repo ]]; then
        "${SUDO[@]}" dnf config-manager --add-repo \
          https://download.docker.com/linux/rhel/docker-ce.repo
      fi
      ;;
    centos|rocky|almalinux)
      repository_distribution="centos"
      echo "Using Docker's CentOS repository for the ${distribution} derivative (best effort)."
      if [[ ! -f /etc/yum.repos.d/docker-ce.repo ]]; then
        "${SUDO[@]}" dnf config-manager --add-repo \
          https://download.docker.com/linux/centos/docker-ce.repo
      fi
      ;;
    *)
      echo "Unsupported RPM distribution: ${distribution}" >&2
      exit 1
      ;;
  esac

  "${SUDO[@]}" dnf install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  echo "Docker packages installed from the official ${repository_distribution} repository."
}

docker_ready=0
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker_ready=1
fi

if [[ "${docker_ready}" == "0" ]]; then
  if [[ "${SKIP_DOCKER_INSTALL}" == "1" ]]; then
    echo "Docker Compose v2 is missing and --skip-docker-install was provided." >&2
    exit 1
  fi
  case "${ID,,}" in
    ubuntu|debian)
      install_docker_apt "${ID,,}"
      ;;
    fedora|rhel|centos|rocky|almalinux)
      install_docker_rpm "${ID,,}"
      ;;
    *)
      echo "Unsupported distribution '${ID}'. Install Docker Compose v2, then rerun with --skip-docker-install." >&2
      exit 1
      ;;
  esac
fi

"${SUDO[@]}" systemctl enable --now docker

if docker info >/dev/null 2>&1; then
  export SIO_DOCKER_USE_SUDO=0
elif "${SUDO[@]}" docker info >/dev/null 2>&1; then
  # We deliberately avoid adding the user to the docker group because it grants
  # root-equivalent access. The installer uses sudo only for this run.
  export SIO_DOCKER_USE_SUDO=1
else
  echo "Docker is installed but its daemon is unavailable." >&2
  exit 1
fi

exec bash "${SCRIPT_DIR}/install-common.sh" "${COMMON_ARGS[@]}"
