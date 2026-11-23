#!/usr/bin/env bash
# Spielt ein Backup zurück. ACHTUNG: überschreibt alle aktuellen Daten!
#   ./scripts/restore.sh data/backups/backup-20261123-023000.dump
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh

FILE="${1:-}"
if [ -z "$FILE" ]; then
  echo "Aufruf: ./scripts/restore.sh data/backups/<datei>.dump"; echo; echo "Vorhandene Backups:"; ls -1 data/backups 2>/dev/null || true; exit 1
fi
[ -f "$FILE" ] || FILE="data/backups/$FILE"
[ -f "$FILE" ] || die "Datei nicht gefunden: $1"
case "$FILE" in *.dump|*.dump.enc) ;; *) die "Nur PostgreSQL-Backups (.dump oder .dump.enc) können so zurückgespielt werden." ;; esac
ENC=0; case "$FILE" in *.enc) ENC=1; [ -n "$(envval BACKUP_PASSPHRASE)" ] || die "BACKUP_PASSPHRASE fehlt in .env – verschlüsselte Backups lassen sich ohne sie nicht zurückspielen." ;; esac
# Entschlüsselt stdin -> stdout (im Backend-Container, dort steht die Passphrase)
decrypt() { docker compose run --rm --no-deps -T backend python -m app.cli decrypt-backup; }

warn "ACHTUNG: Alle aktuellen Daten werden durch den Stand von '$FILE' ersetzt."
read -r -p "Zum Fortfahren bitte JA eingeben: " ANSWER
[ "$ANSWER" = "JA" ] || die "Abgebrochen."

say "Sicherheits-Backup des aktuellen Stands"
./scripts/backup.sh || die "Sicherheits-Backup fehlgeschlagen – Wiederherstellung abgebrochen."

say "Anwendung wird angehalten"
docker compose stop web backend

say "Datenbank wird neu angelegt und befüllt"
docker compose exec -T db psql -U dienstplan -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS dienstplan WITH (FORCE);" \
  -c "CREATE DATABASE dienstplan OWNER dienstplan;"
if [ "$ENC" = "1" ]; then
  decrypt < "$FILE" | docker compose exec -T db pg_restore -U dienstplan -d dienstplan --no-owner --exit-on-error
else
  docker compose exec -T db pg_restore -U dienstplan -d dienstplan --no-owner --exit-on-error < "$FILE"
fi

BASE="${FILE%.enc}"; BASE="${BASE%.dump}"
FILES=""
for cand in "$BASE.files.tar.gz.enc" "$BASE.files.tar.gz"; do [ -f "$cand" ] && { FILES="$cand"; break; }; done
if [ -n "$FILES" ]; then
  say "Dokumente werden zurückgespielt"
  rm -rf data/documents.old && { [ -d data/documents ] && mv data/documents data/documents.old || true; }
  case "$FILES" in
    *.enc) decrypt < "$FILES" | docker compose run --rm --no-deps -T backend sh -c "tar -xzf - -C /data" ;;
    *)     docker compose run --rm --no-deps -T backend sh -c "tar -xzf - -C /data" < "$FILES" ;;
  esac || warn "Dokumente konnten nicht zurückgespielt werden. Der vorherige Stand liegt in data/documents.old"
else
  warn "Keine Dokumenten-Sicherung zu diesem Backup gefunden – Dokumente bleiben unverändert."
fi

say "Anwendung wird gestartet"
docker compose up -d backend web
wait_healthy backend 180 || die "Backend startet nicht. Prüfen mit: docker compose logs backend"
say "Fertig. Der Stand von '$FILE' ist wiederhergestellt."
