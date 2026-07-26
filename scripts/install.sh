#!/usr/bin/env bash

# Portable entrypoint for Unix-like hosts. Windows users should run
# install-windows.ps1 from PowerShell instead.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$(uname -s)" in
  Linux)
    exec bash "${SCRIPT_DIR}/install-linux.sh" "$@"
    ;;
  Darwin)
    exec bash "${SCRIPT_DIR}/install-macos.sh" "$@"
    ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "Run scripts/install-windows.ps1 from PowerShell on Windows." >&2
    exit 1
    ;;
  *)
    echo "Unsupported operating system: $(uname -s)" >&2
    exit 1
    ;;
esac
