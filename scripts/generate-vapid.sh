#!/usr/bin/env bash
# Erzeugt Schlüssel für Push-Nachrichten (optional) und trägt sie in .env ein.
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(docker compose run --rm --no-deps -T --entrypoint python backend -m app.cli gen-vapid)
priv=$(echo "$out" | grep ^VAPID_PRIVATE_KEY= | cut -d= -f2-)
pub=$(echo "$out" | grep ^VAPID_PUBLIC_KEY= | cut -d= -f2-)
sed -i -e "s|^VAPID_PRIVATE_KEY=.*|VAPID_PRIVATE_KEY=${priv}|" -e "s|^VAPID_PUBLIC_KEY=.*|VAPID_PUBLIC_KEY=${pub}|" .env
docker compose up -d backend
echo "Push-Schlüssel eingetragen. Benutzer können in ihrem Profil „Benachrichtigungen aktivieren“ wählen."
