#!/usr/bin/env bash
# Installiert den Dienstplan auf einem Ubuntu/Debian-Server. Aufruf als root:
#   sudo ./scripts/install.sh
# Ohne Rückfragen: DOMAIN=… COMPANY=… ADMIN_NAME=… ADMIN_EMAIL=… ADMIN_PASSWORD=… sudo -E ./scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh

[ "$(id -u)" -eq 0 ] || die "Bitte als root starten:  sudo ./scripts/install.sh"
command -v apt-get >/dev/null 2>&1 || die "Automatische Installation gibt es nur für Debian/Ubuntu. Siehe README (manuelle Installation)."
[ -f docker-compose.yml ] || die "Bitte im Projektordner ausführen (hier fehlt docker-compose.yml)."

say "1/7 Voraussetzungen (Docker, cron, openssl)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y curl ca-certificates openssl cron >/dev/null
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || apt-get install -y docker-compose-plugin >/dev/null || die "Docker Compose Plugin konnte nicht installiert werden."
systemctl enable --now docker >/dev/null 2>&1 || true
systemctl enable --now cron >/dev/null 2>&1 || true

say "2/7 Konfiguration (.env)"
if [ -f .env ]; then
  warn ".env existiert bereits und wird beibehalten."
else
  DOMAIN="${DOMAIN:-}"
  if [ -z "$DOMAIN" ]; then
    read -r -p "Domain dieses Servers (z. B. dienstplan.meinefirma.de; leer = nur Test per http://SERVER-IP): " DOMAIN
  fi
  if [ -z "$DOMAIN" ]; then
    SERVER_IP="$(hostname -I | awk '{print $1}')"
    SITE=":80"; APP_URL="http://${SERVER_IP}"; SECURE="false"
    warn "Ohne Domain gibt es kein HTTPS: Die App lässt sich dann NICHT als App installieren und Passwörter laufen unverschlüsselt. Nur zum Testen!"
  else
    SITE="$DOMAIN"; APP_URL="https://${DOMAIN}"; SECURE="true"
  fi
  umask 077
  cp .env.example .env
  sed -i \
    -e "s|^DOMAIN=.*|DOMAIN=${SITE}|" \
    -e "s|^APP_URL=.*|APP_URL=${APP_URL}|" \
    -e "s|^COOKIE_SECURE=.*|COOKIE_SECURE=${SECURE}|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" .env
  chmod 600 .env
fi

ensure_secrets

say "3/7 Ordner für Backups und Protokolle"
mkdir -p data/backups data/logs data/documents
chown -R 10001:10001 data

say "4/7 Programm wird gebaut (das dauert beim ersten Mal einige Minuten)"
docker compose build

if [ -z "$(envval VAPID_PRIVATE_KEY)" ]; then
  say "Push-Schlüssel werden erzeugt"
  KEYS="$(docker compose run --rm --no-deps backend python -m app.cli gen-vapid)"
  PRIV="$(echo "$KEYS" | grep '^VAPID_PRIVATE_KEY=' | cut -d= -f2-)"
  PUB="$(echo "$KEYS" | grep '^VAPID_PUBLIC_KEY=' | cut -d= -f2-)"
  if [ -n "$PRIV" ] && [ -n "$PUB" ]; then
    sed -i -e "s|^VAPID_PRIVATE_KEY=.*|VAPID_PRIVATE_KEY=${PRIV}|" -e "s|^VAPID_PUBLIC_KEY=.*|VAPID_PUBLIC_KEY=${PUB}|" .env
  else
    warn "Push-Schlüssel konnten nicht erzeugt werden (Push bleibt aus, alles andere funktioniert)."
  fi
fi

say "5/7 Dienste starten"
docker compose up -d
wait_healthy backend 240 || { docker compose logs --tail=60 backend; die "Das Backend ist nicht gestartet. Siehe Meldungen oben."; }

say "6/7 Firma und erster Administrator"
ADMIN_PASS_SHOWN=""
if docker compose exec -T backend python -c "import sys; from app.db import SessionLocal; from app.models import User; from sqlalchemy import select; sys.exit(0 if SessionLocal().scalar(select(User.id)) else 1)" >/dev/null 2>&1; then
  warn "Es gibt bereits Benutzer – Firma und Administrator werden nicht neu angelegt."
else
  COMPANY="${COMPANY:-}"; ADMIN_NAME="${ADMIN_NAME:-}"; ADMIN_EMAIL="${ADMIN_EMAIL:-}"; ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
  if [ -z "$COMPANY" ];     then read -r -p "Firmenname [physio & fit VitalZentrum Eschweiler]: " COMPANY; fi
  COMPANY="${COMPANY:-physio & fit VitalZentrum Eschweiler}"
  [ -n "$ADMIN_NAME" ]  || read -r -p "Name des Administrators: " ADMIN_NAME
  [ -n "$ADMIN_EMAIL" ] || read -r -p "E-Mail des Administrators (dient als Login): " ADMIN_EMAIL
  if [ -z "$ADMIN_PASSWORD" ]; then
    read -r -s -p "Passwort (mind. 10 Zeichen mit Buchstaben und Ziffern; leer = zufällig erzeugen): " ADMIN_PASSWORD; echo
  fi
  if [ -z "$ADMIN_PASSWORD" ]; then
    # "x7" am Ende garantiert Buchstabe + Ziffer (Passwortregel)
    ADMIN_PASSWORD="$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 14)x7"
    ADMIN_PASS_SHOWN="$ADMIN_PASSWORD"
  fi
  # Passwort über die Umgebung übergeben (steht so nicht in der Prozessliste)
  docker compose exec -T -e ADMIN_PASSWORD="$ADMIN_PASSWORD" backend python -m app.cli setup-company \
    --company "$COMPANY" --email "$ADMIN_EMAIL" --name "$ADMIN_NAME" || die "Firma/Administrator konnten nicht angelegt werden (Passwortregel beachten)."
fi

say "7/7 Automatische Backups und Überwachung"
ROOT="$(pwd)"
cat > /etc/cron.d/dienstplan <<CRON
# Dienstplan: tägliches Backup und Gesundheitsprüfung alle 5 Minuten
0 2 * * * root cd ${ROOT} && ./scripts/backup.sh >> data/logs/backup.log 2>&1
*/5 * * * * root cd ${ROOT} && ./scripts/healthcheck.sh >> data/logs/healthcheck.log 2>&1
CRON
chmod 644 /etc/cron.d/dienstplan
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
fi

URL="$(envval APP_URL)"
printf '\n\033[1;32m=============================================\n Installation abgeschlossen\n=============================================\033[0m\n'
echo " Adresse:      ${URL}"
if [ -n "${ADMIN_EMAIL:-}" ]; then echo " Login:        ${ADMIN_EMAIL}"; fi
if [ -n "$ADMIN_PASS_SHOWN" ]; then
  echo " Passwort:     ${ADMIN_PASS_SHOWN}"
  warn " Bitte notieren und nach der ersten Anmeldung unter 'Profil' ändern. Es wird nicht erneut angezeigt."
fi
echo " Backups:      täglich 02:00 Uhr in ${ROOT}/data/backups"
echo " Hilfe:        docs/WARTUNG.md"
