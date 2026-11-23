# Dienstplan – Backend (Etappe 2)

FastAPI + SQLAlchemy 2 + PostgreSQL (SQLite für Entwicklung/Tests).

## Lokal starten (Entwicklung)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.cli seed-demo            # Demo-Betrieb mit Beispieldaten
uvicorn app.main:app --reload          # API-Doku: http://localhost:8000/api/docs
```
Demo-Logins (Passwort `Demo-Passwort-1234`): `admin@demo.local`, `planer@demo.local`, `anna@demo.local`.

## Einrichtung für die eigene Firma (Einzelbetrieb)
```bash
python -m app.cli setup-company --email chef@example.de --name "Vorname Nachname" --password 'Mindestens-10-Zeichen1'
```
Legt "physio & fit VitalZentrum Eschweiler" mit den Abteilungen *Physiotherapie* und *Fitness* an
(Namen im Adminbereich änderbar oder per `--departments "A,B"`). Danach sind keine weiteren Firmen
möglich (`ALLOW_TENANT_REGISTRATION=false`). Mitarbeiter legt der Administrator in der App an.

## Tests
```bash
pytest -v
```

## Rollen
- **admin**: alle Rechte (fest).
- **mitarbeiter**: Planer/Büro (Schichten, Freigaben, Berichte) – Rechte anpassbar.
- **benutzer**: Schichtmitarbeiter (eigener Plan, Tausch, Urlaub, Stempeln) – Rechte anpassbar.

## Wichtige Entwurfsentscheidungen
- Anmeldung: JWT in HttpOnly-Cookie + CSRF-Token (Double-Submit, Header `X-CSRF-Token`); Argon2-Hashes.
- Sitzungen enden bei Passwortänderung, Sperrung und Rollenänderung (`token_version`).
- Gleichzeitige Änderungen: optimistische Sperre über `version`; bei Konflikt HTTP 409.
- Zeiten: UTC, Ausgabe als ISO-8601 mit `Z`.
- Löschen: Benutzer werden anonymisiert (DSGVO), Schichten per Soft-Delete.
- Echtzeit: WebSocket `/api/ws` meldet `shifts.changed`, `swaps.changed`, `leave.changed` usw.
- Einzelbetrieb: Es gibt genau eine Firma (Ersteinrichtung), weitere nur mit `ALLOW_TENANT_REGISTRATION=true` (nicht empfohlen).
- Passwort-Reset: Link per SMTP; ohne SMTP landet er im Server-Log.
- Rate-Limit ist pro Prozess (bei mehreren Workern pro Worker).
- Migrationen: `alembic upgrade head` (Baseline `0001`); neue Änderungen mit `alembic revision --autogenerate`.
- Wiederherstellen eines Backups geschieht bewusst per Skript (Etappe 4), nicht per API.
