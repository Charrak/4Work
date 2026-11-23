#!/bin/sh
set -e
# Datenbankmigrationen anwenden (wartet, bis PostgreSQL bereit ist)
i=0
until alembic upgrade head; do
  i=$((i+1))
  if [ "$i" -ge 30 ]; then echo "Datenbank nicht erreichbar - Abbruch"; exit 1; fi
  echo "Warte auf Datenbank ($i/30) ..."
  sleep 2
done
# Bewusst genau EIN Worker: WebSocket-Hub und Rate-Limit liegen im Arbeitsspeicher des Prozesses.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
  --no-proxy-headers --no-server-header
