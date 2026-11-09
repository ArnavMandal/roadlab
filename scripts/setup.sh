#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r worker/requirements-lock.txt
(cd relay && go mod download && go build -o ../bin/relay .)
(cd web && npm ci)
.venv/bin/python -m worker.fixtures
printf '\nReady. Start PostgreSQL with docker compose up -d, then run scripts/start.sh.\n'
