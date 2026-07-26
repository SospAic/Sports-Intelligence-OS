#!/usr/bin/env bash

# Shared, idempotent project bootstrap used by the Linux and macOS installers.
# The operating-system wrapper must make a working Docker Compose v2 available first.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
STATE_DIR="${PROJECT_ROOT}/.sio"
STATE_FILE="${STATE_DIR}/install-state"
RULE_FILE="/workspace/data/rules/ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt"

ADMIN_EMAIL="${SIO_INSTALL_ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${SIO_INSTALL_ADMIN_PASSWORD:-}"
WORKSPACE_NAME="${SIO_INSTALL_WORKSPACE_NAME:-Sports Intelligence OS}"
WITH_DEMO_DATA=0
SKIP_BOOTSTRAP=0
WAIT_SECONDS="${SIO_INSTALL_WAIT_SECONDS:-300}"

usage() {
  cat <<'EOF'
Sports Intelligence OS project bootstrap

Usage: install-common.sh [options]
  --admin-email EMAIL       Initial administrator email
  --admin-password VALUE    Initial password (randomly generated when omitted)
  --workspace-name NAME     Initial workspace name
  --with-demo-data          Add clearly labelled Mock monitoring records
  --skip-bootstrap          Keep an existing administrator; skip account creation
  --wait-seconds SECONDS    Service readiness timeout (default: 300)
  -h, --help                Show this help

Environment equivalents:
  SIO_INSTALL_ADMIN_EMAIL, SIO_INSTALL_ADMIN_PASSWORD,
  SIO_INSTALL_WORKSPACE_NAME, SIO_INSTALL_WAIT_SECONDS.
EOF
}

while (($#)); do
  case "$1" in
    --admin-email)
      ADMIN_EMAIL="${2:?--admin-email requires a value}"
      shift 2
      ;;
    --admin-password)
      ADMIN_PASSWORD="${2:?--admin-password requires a value}"
      shift 2
      ;;
    --workspace-name)
      WORKSPACE_NAME="${2:?--workspace-name requires a value}"
      shift 2
      ;;
    --with-demo-data)
      WITH_DEMO_DATA=1
      shift
      ;;
    --skip-bootstrap)
      SKIP_BOOTSTRAP=1
      shift
      ;;
    --wait-seconds)
      WAIT_SECONDS="${2:?--wait-seconds requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "${WAIT_SECONDS}" in
  ''|*[!0-9]*)
    echo "--wait-seconds must be a positive integer" >&2
    exit 2
    ;;
esac
if ((WAIT_SECONDS < 30)); then
  echo "--wait-seconds must be at least 30" >&2
  exit 2
fi

for command_name in docker curl openssl awk grep; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done

docker_compose() {
  if [[ "${SIO_DOCKER_USE_SUDO:-0}" == "1" ]]; then
    sudo docker compose "$@"
  else
    docker compose "$@"
  fi
}

set_env_value() {
  local key="$1"
  local value="$2"
  local file="$3"
  local temporary
  temporary="$(mktemp "${file}.XXXXXX")"
  awk -v key="${key}" -v value="${value}" '
    BEGIN { replaced = 0 }
    $0 ~ ("^" key "=") {
      print key "=" value
      replaced = 1
      next
    }
    { print }
    END {
      if (!replaced) print key "=" value
    }
  ' "${file}" >"${temporary}"
  mv "${temporary}" "${file}"
}

random_hex() {
  openssl rand -hex "$1"
}

random_urlsafe_key() {
  openssl rand -base64 32 | tr '+/' '-_' | tr -d '\r\n'
}

cd "${PROJECT_ROOT}"

if ! docker_compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required. The command 'docker compose version' failed." >&2
  exit 1
fi

created_env=0
if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${PROJECT_ROOT}/.env.example" "${ENV_FILE}"
  postgres_password="$(random_hex 24)"
  signing_key="$(random_hex 48)"
  notification_key="$(random_urlsafe_key)"
  set_env_value POSTGRES_PASSWORD "${postgres_password}" "${ENV_FILE}"
  set_env_value SIO_DATABASE_URL "postgresql+asyncpg://sio:${postgres_password}@127.0.0.1:5432/sports_intelligence" "${ENV_FILE}"
  set_env_value SIO_SECRET_KEY "${signing_key}" "${ENV_FILE}"
  set_env_value SIO_NOTIFICATION_ENCRYPTION_KEY "${notification_key}" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}" 2>/dev/null || true
  created_env=1
  echo "Created .env with random local secrets. The file is excluded from Git."
else
  echo "Preserving the existing .env file without rotating credentials."
fi

if [[ "${created_env}" == "0" ]] && grep -q '^POSTGRES_PASSWORD=sio-local-development-only$' "${ENV_FILE}"; then
  echo "WARNING: the existing .env still contains the development database password." >&2
fi

echo "Validating Docker Compose configuration..."
docker_compose config --quiet

echo "Building and starting PostgreSQL, Redis, API, Worker, Beat, Web and Caddy..."
docker_compose up -d --build

echo "Waiting for the API readiness check..."
deadline=$((SECONDS + WAIT_SECONDS))
until curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:8000/health/ready >/dev/null 2>&1; do
  if ((SECONDS >= deadline)); then
    echo "Services did not become ready within ${WAIT_SECONDS} seconds." >&2
    docker_compose ps >&2 || true
    docker_compose logs --tail=80 api postgres redis >&2 || true
    exit 1
  fi
  sleep 3
done

mkdir -p "${STATE_DIR}"
generated_password=0
admin_created=0
if [[ "${SKIP_BOOTSTRAP}" == "1" ]]; then
  echo "Skipping administrator creation as requested."
elif [[ -f "${STATE_FILE}" ]]; then
  echo "Installer state exists; preserving the existing administrator."
else
  if [[ -z "${ADMIN_PASSWORD}" ]]; then
    ADMIN_PASSWORD="Sio!7$(random_hex 10)"
    generated_password=1
  fi
  echo "Creating the initial administrator and workspace..."
  docker_compose run --rm \
    -e "SIO_BOOTSTRAP_ADMIN_EMAIL=${ADMIN_EMAIL}" \
    -e "SIO_BOOTSTRAP_ADMIN_PASSWORD=${ADMIN_PASSWORD}" \
    -e "SIO_BOOTSTRAP_WORKSPACE_NAME=${WORKSPACE_NAME}" \
    api python -m app.cli bootstrap-admin
  {
    printf 'installed_at=%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    printf 'admin_email=%s\n' "${ADMIN_EMAIL}"
  } >"${STATE_FILE}"
  chmod 600 "${STATE_FILE}" 2>/dev/null || true
  admin_created=1
fi

echo "Loading idempotent platform, rule, Prompt, news-source and automation defaults..."
docker_compose run --rm api python -m app.cli seed-platforms
docker_compose run --rm api python -m app.cli import-rules --file "${RULE_FILE}"
docker_compose run --rm api python -m app.cli seed-generation
docker_compose run --rm api python -m app.cli seed-news-sources
docker_compose run --rm api python -m app.cli seed-automations

if [[ "${WITH_DEMO_DATA}" == "1" ]]; then
  echo "Adding explicitly labelled DEMO/MOCK monitoring data..."
  docker_compose run --rm api python -m app.cli seed-demo-monitoring
else
  echo "Demo data was not installed. Use --with-demo-data to opt in to labelled Mock records."
fi

echo "Verifying all Compose services and the unified web entrypoint..."
running_services="$(docker_compose ps --status running --services)"
for service_name in postgres redis api worker beat web proxy; do
  if ! printf '%s\n' "${running_services}" | grep -qx "${service_name}"; then
    echo "Compose service is not running: ${service_name}" >&2
    docker_compose ps >&2 || true
    docker_compose logs --tail=80 "${service_name}" >&2 || true
    exit 1
  fi
done

web_deadline=$((SECONDS + 60))
until curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:8080/login >/dev/null 2>&1; do
  if ((SECONDS >= web_deadline)); then
    echo "The unified web entrypoint did not become ready within 60 seconds." >&2
    docker_compose logs --tail=80 web proxy >&2 || true
    exit 1
  fi
  sleep 3
done

echo
echo "Sports Intelligence OS is ready:"
echo "  Web:    http://localhost:8080"
echo "  API:    http://127.0.0.1:8000/docs"
echo "  Health: http://127.0.0.1:8000/health/ready"
if [[ "${admin_created}" == "1" && "${generated_password}" == "1" ]]; then
  echo "  Admin:  ${ADMIN_EMAIL}"
  echo "  One-time generated password: ${ADMIN_PASSWORD}"
  echo "Store this password now. It is not written to the repository or installer state."
elif [[ "${admin_created}" == "1" ]]; then
  echo "  Admin:  ${ADMIN_EMAIL}"
fi
