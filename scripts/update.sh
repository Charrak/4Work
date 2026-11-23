#!/usr/bin/env bash
# Sicheres Update: Backup -> neuen Code holen -> neu bauen -> starten (Datenbankmigrationen laufen automatisch).
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh

say "1/4 Backup vor dem Update"
./scripts/backup.sh || die "Backup fehlgeschlagen – Update abgebrochen (es wurde nichts verändert)."

say "2/4 Neuen Programmstand holen"
if [ -d .git ]; then
  git pull --ff-only
else
  warn "Kein Git-Repository. Kopieren Sie den neuen Programmstand vorher in diesen Ordner (data/ und .env NICHT überschreiben)."
fi

say "3/4 Neu bauen und starten"
ensure_secrets
docker compose build --pull
docker compose up -d

say "4/4 Prüfen"
wait_healthy backend 240 || { docker compose logs --tail=80 backend; die "Backend startet nach dem Update nicht. Rückgängig: siehe docs/WARTUNG.md (Abschnitt Rollback)."; }
# Bereits vorhandene (ältere, unverschlüsselte) Dokumente nachträglich verschlüsseln – harmlos bei Wiederholung
docker compose exec -T backend python -m app.cli encrypt-documents || warn "Bestehende Dokumente konnten nicht verschlüsselt werden (siehe Meldung)."
docker image prune -f >/dev/null
docker compose ps
say "Update abgeschlossen."
