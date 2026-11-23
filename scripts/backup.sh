#!/usr/bin/env bash
# Erstellt ein Datenbank-Backup in data/backups (alte werden automatisch gelöscht, siehe BACKUP_KEEP).
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh

echo "$(date '+%F %T') Backup startet"
docker compose exec -T backend python -m app.cli backup

TARGET="$(envval BACKUP_RSYNC_TARGET)"
if [ -n "$TARGET" ]; then
  echo "Kopie nach $TARGET"
  rsync -a data/backups/ "$TARGET"
fi
echo "$(date '+%F %T') Backup fertig"
