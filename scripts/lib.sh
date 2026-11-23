# Gemeinsame Hilfsfunktionen (wird von den anderen Skripten eingebunden)
say()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mFehler: %s\033[0m\n' "$*" >&2; exit 1; }

# Wert aus .env lesen, ohne die Datei als Shell-Skript auszuführen
envval() { grep -E "^$1=" .env 2>/dev/null | head -n1 | cut -d= -f2- || true; }

wait_healthy() {  # wait_healthy <service> <sekunden>
  local svc="$1" max="${2:-180}" waited=0 cid status
  while [ "$waited" -lt "$max" ]; do
    cid="$(docker compose ps -q "$svc" 2>/dev/null || true)"
    if [ -n "$cid" ]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      case "$status" in healthy|running) return 0 ;; esac
    fi
    sleep 3; waited=$((waited + 3))
  done
  return 1
}

# Fehlende Geheimnisse in .env ergänzen (idempotent). Setzt NEW_SECRETS=1, wenn etwas erzeugt wurde.
NEW_SECRETS=0
ensure_env_secret() {  # ensure_env_secret NAME 'Befehl, der den Wert ausgibt'
  local name="$1" gen="$2" val
  [ -n "$(envval "$name")" ] && return 0
  val="$(eval "$gen")"
  [ -n "$val" ] || die "Konnte $name nicht erzeugen."
  if grep -qE "^${name}=" .env; then sed -i "s|^${name}=.*|${name}=${val}|" .env
  else printf '\n%s=%s\n' "$name" "$val" >> .env; fi
  NEW_SECRETS=1
}
ensure_secrets() {
  [ -f .env ] || return 0
  ensure_env_secret BACKUP_PASSPHRASE 'openssl rand -hex 24'
  ensure_env_secret DOCUMENTS_KEY 'openssl rand -base64 32 | tr "+/" "-_"'
  chmod 600 .env
  if [ "$NEW_SECRETS" = "1" ]; then
    warn "WICHTIG: Es wurden neue Schlüssel in .env erzeugt (BACKUP_PASSPHRASE, DOCUMENTS_KEY)."
    warn "Sichern Sie diese Zeilen JETZT an einem sicheren Ort AUSSERHALB des Servers (z. B. Passwortmanager)."
    warn "Ohne sie lassen sich Backups und Dokumente NICHT wiederherstellen."
  fi
}
