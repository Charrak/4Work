# Dienstplan – physio & fit VitalZentrum Eschweiler

Eigene Dienstplan-Software (Schichtplanung, Tausch, Urlaub, Zeiterfassung, Chat, Berichte) für **eine Firma mit zwei Abteilungen**
(Physiotherapie, Fitness – umbenennbar). Läuft auf einem eigenen Linux-Server, alle Geräte arbeiten mit denselben Daten
und werden automatisch synchron gehalten. Als App installierbar auf Android, iPhone/iPad, Windows, macOS (Linux: Browser).

Referenz für den Funktionsumfang war die Shiftbase Dienstplan-App; Code, Texte und Gestaltung sind eigenständig.

## Schnellstart (Server, 4 Befehle)
Voraussetzung: Linux-Server (Ubuntu/Debian), root-Zugang, eine Domain, die auf den Server zeigt, Ports 80 und 443 frei.
```bash
# Projektordner auf den Server kopieren (z. B. per scp/Git), dann:
cd dienstplan
sudo ./scripts/install.sh      # fragt Domain und Administrator ab, installiert Docker, startet alles
./scripts/smoke-test.sh        # Funktionstest
```
Danach `https://<Ihre-Domain>` öffnen und anmelden. Ausführlich: [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Dokumentation
| Datei | Inhalt |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Schritt für Schritt auf VPS / eigenem Server, Domain, E-Mail, Push |
| [docs/BEDIENUNG.md](docs/BEDIENUNG.md) | Bedienungsanleitung für Administrator, Planer und Mitarbeiter |
| [docs/WARTUNG.md](docs/WARTUNG.md) | Backups, Wiederherstellung, Updates, Überwachung, Fehlersuche |
| [docs/API.md](docs/API.md) | API-Überblick (interaktive Doku nur in der Entwicklung; in Produktion per `ENABLE_API_DOCS=true`) |
| [docs/DSGVO.md](docs/DSGVO.md) | Datenschutz-Hinweise, Löschkonzept |
| [docs/SICHERHEIT.md](docs/SICHERHEIT.md) | Sicherheits-Selbstprüfung (kein unabhängiges Audit), Betreiber-Checkliste |
| [docs/PENTEST.md](docs/PENTEST.md) | Vorbereitung eines unabhängigen Penetrationstests (Umfang, Vorgehen) |
| [docs/ENTSCHEIDUNGEN.md](docs/ENTSCHEIDUNGEN.md) | Technische Entscheidungen, Grenzen, Teststatus |

## Projektstruktur
```
backend/    FastAPI, SQLAlchemy, Alembic, Tests (pytest)
frontend/   React + TypeScript + Vite, PWA (Manifest, Service Worker, Icons)
deploy/     Caddyfile (HTTPS, Reverse-Proxy), Dockerfile für das Web-Image
scripts/    install, backup, restore, update, healthcheck, smoke-test
docs/       Anleitungen
branding/   Original-Logo
docker-compose.yml, .env.example
```

## Entwicklung (ohne Docker)
Backend: `cd backend && pip install -r requirements-dev.txt && pytest -v && python -m app.cli seed-demo && uvicorn app.main:app --reload`
Frontend: `cd frontend && npm install && npm run dev` → http://localhost:5173
Demo-Logins (Passwort `Demo-Passwort-1234`): `admin@demo.local`, `planer@demo.local`, `anna@demo.local`.
