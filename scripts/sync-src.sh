#!/usr/bin/env bash
# Push host-side apps/api sources into the running api+worker containers.
#
# The images are rebuilt offline (see AGENTS.md) because PyPI is unreachable from
# this network, so `docker cp` is the supported way to iterate on Python code.
# Always pass repo-relative paths, e.g.:
#   scripts/sync-src.sh apps/api/app/services/sync.py apps/api/tests/test_x.py
set -euo pipefail

cd "$(dirname "$0")/.."

API=$(docker compose ps -q api)
WORKER=$(docker compose ps -q worker)

if [ -z "$API" ] || [ -z "$WORKER" ]; then
  echo "api/worker container not running" >&2
  exit 1
fi

for f in "$@"; do
  [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
  # `docker cp` refuses to create intermediate directories, and the two images
  # do not carry an identical tree (worker ships no scripts/), so make the
  # destination first or the copy fails with "Could not find the file".
  dir=$(dirname "$f")
  for c in "$API" "$WORKER"; do
    docker exec "$c" mkdir -p /workspace/"$dir" >/dev/null 2>&1 || true
    docker cp "$f" "$c":/workspace/"$f" >/dev/null
  done
  echo "  -> $f"
done

echo "synced ${#} file(s) to api + worker"
