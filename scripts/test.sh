#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TEST_DATABASE_URL:?Set TEST_DATABASE_URL to a local PostgreSQL database; tests create isolated schemas.}"
(cd relay && go test -race -v ./...)
"${PYTHON:-.venv/bin/python}" -m unittest discover -s worker -t . -v
(cd web && npm run build)
