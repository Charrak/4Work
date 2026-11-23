#!/usr/bin/env bash
# Prüft, ob die Anwendung antwortet; startet sie bei Bedarf neu. Läuft per cron alle 5 Minuten.
set -uo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh

DOMAIN="$(envval DOMAIN)"
check() {
  if [ "${DOMAIN#:}" != "$DOMAIN" ]; then   # ":80" = Test ohne HTTPS
    curl -fsS -m 10 "http://127.0.0.1/api/health" >/dev/null 2>&1
  else
    curl -fsS -m 10 --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/api/health" >/dev/null 2>&1
  fi
}

if check; then exit 0; fi
echo "$(date '+%F %T') Keine Antwort – Dienste werden gestartet"
docker compose up -d >/dev/null 2>&1
sleep 30
if check; then
  echo "$(date '+%F %T') Wieder erreichbar"
  exit 0
fi
echo "$(date '+%F %T') FEHLER: weiterhin nicht erreichbar"
ALERT="$(envval ALERT_EMAIL)"
if [ -n "$ALERT" ] && command -v mail >/dev/null 2>&1; then
  echo "Der Dienstplan auf $(hostname) ist nicht erreichbar." | mail -s "Dienstplan Ausfall" "$ALERT"
fi
exit 1
