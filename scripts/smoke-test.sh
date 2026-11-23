#!/usr/bin/env bash
# Funktionstest nach Installation/Update: prüft Erreichbarkeit, PWA-Dateien und Sicherheits-Header.
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
D="${DOMAIN:-localhost}"
if [ "${D#:}" != "$D" ]; then BASE="http://127.0.0.1"; PLAIN=1; else BASE="https://$D"; PLAIN=0; fi
C="curl -sS --max-time 15"; [ "$D" = "localhost" ] && C="$C -k"
fail=0
check() { # check "Beschreibung" Befehl...
  local d="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "ok:      $d"; else echo "FEHLER:  $d"; fail=1; fi
}
check "Startseite"                     $C -f "$BASE/"
check "API-Gesundheit"                 $C -f "$BASE/api/health"
check "Manifest (PWA)"                 $C -f "$BASE/manifest.webmanifest"
check "Service Worker"                 $C -f "$BASE/sw.js"
check "App-Symbol 512"                 $C -f "$BASE/icons/icon-512.png"
check "SPA-Fallback (/plan)"           $C -f "$BASE/plan"
check "API verlangt Anmeldung (401)"   bash -c "[ \"\$($C -o /dev/null -w '%{http_code}' $BASE/api/users)\" = 401 ]"
[ "$PLAIN" = 1 ] || check "HSTS-Header gesetzt"            bash -c "$C -I $BASE/ | grep -qi strict-transport-security"
check "Backend nicht direkt erreichbar" bash -c "! curl -s --max-time 3 http://localhost:8000/api/health"
[ $fail = 0 ] && echo "Alles in Ordnung." || echo "Es gab Fehler (siehe oben)."
exit $fail
