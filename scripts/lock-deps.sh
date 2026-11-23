#!/usr/bin/env bash
# Fixiert alle Abhängigkeiten auf exakte Versionen mit Prüfsummen (requirements.lock, package-lock.json).
# Braucht Internet und Docker. Einmal ausführen, Ergebnis ins Repository übernehmen, danach nur bei Updates erneut.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh

say "Python: requirements.lock (mit Hashes)"
docker run --rm -v "$PWD/backend:/w" -w /w python:3.12-slim-bookworm sh -c \
  "pip install -q pip-tools && pip-compile -q --generate-hashes --allow-unsafe --strip-extras -o requirements.lock requirements.txt && pip-compile -q --generate-hashes --allow-unsafe --strip-extras -o requirements-dev.lock requirements-dev.txt"

say "Frontend: package-lock.json"
docker run --rm -v "$PWD/frontend:/w" -w /w node:22-alpine npm install --package-lock-only --no-audit --no-fund

say "Fertig. Bitte requirements*.lock und package-lock.json einchecken und committen."
