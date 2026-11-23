#!/usr/bin/env bash
# Prüft Abhängigkeiten auf bekannte Schwachstellen (CVEs). Braucht Internet. Rückgabewert ≠ 0 bei Funden.
set -uo pipefail
cd "$(dirname "$0")/.."
rc=0
echo "== Python (pip-audit) =="
docker run --rm -v "$PWD/backend:/w" -w /w python:3.12-slim-bookworm sh -c \
  "pip install -q pip-audit && pip-audit -r $( [ -f backend/requirements.lock ] && echo requirements.lock || echo requirements.txt )" || rc=1
echo "== Frontend (npm audit) =="
docker run --rm -v "$PWD/frontend:/w" -w /w node:22-alpine sh -c "npm install --package-lock-only --no-audit --no-fund >/dev/null 2>&1; npm audit --omit=dev" || rc=1
exit $rc
