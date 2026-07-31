$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is required. Install/start Docker Desktop and ensure docker is on PATH."
}

docker compose up --build
