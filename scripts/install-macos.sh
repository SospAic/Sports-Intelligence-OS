#!/usr/bin/env bash

# Installs Docker Desktop through Homebrew when necessary, waits for the local
# daemon, then delegates project setup to install-common.sh.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_DOCKER_INSTALL=0
COMMON_ARGS=()

while (($#)); do
  case "$1" in
    -h|--help)
      bash "${SCRIPT_DIR}/install-common.sh" --help
      echo "  --skip-docker-install   Require an existing Docker Desktop and Compose v2"
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

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is only for macOS." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  if [[ "${SKIP_DOCKER_INSTALL}" == "1" ]]; then
    echo "Docker is missing and --skip-docker-install was provided." >&2
    exit 1
  fi
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required to install Docker Desktop automatically." >&2
    echo "Install Homebrew from https://brew.sh or install Docker Desktop manually." >&2
    exit 1
  fi
  brew install --cask docker
fi

if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop. Its first-run terms may require your confirmation..."
  open -a Docker
  deadline=$((SECONDS + 300))
  until docker info >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      echo "Docker Desktop did not become ready within 300 seconds." >&2
      echo "Complete its first-run setup, then rerun this installer." >&2
      exit 1
    fi
    sleep 3
  done
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Desktop is running, but Docker Compose v2 is unavailable." >&2
  exit 1
fi

export SIO_DOCKER_USE_SUDO=0
exec bash "${SCRIPT_DIR}/install-common.sh" "${COMMON_ARGS[@]}"
