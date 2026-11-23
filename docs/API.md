# API-Überblick

Die interaktive Dokumentation (OpenAPI) liegt unter **`/api/docs`** (Swagger), `/api/redoc` und `/api/openapi.json`. **Im Produktivbetrieb ist sie standardmäßig abgeschaltet** (`ENABLE_API_DOCS=false`); zum Ansehen kurz `ENABLE_API_DOCS=true` in `.env` setzen und `docker compose up -d backend` ausführen – oder lokal mit `ENV=development` starten. Dieses Dokument bleibt der Überblick.

**Authentifizierung:** `POST /api/auth/login` setzt ein HttpOnly-Cookie (`access_token`) und ein lesbares Cookie `csrf_token`. Alle schreibenden Aufrufe (POST/PATCH/PUT/DELETE) müssen den Header `X-CSRF-Token` mit dem Wert des Cookies senden. Alternativ ist `Authorization: Bearer <token>` möglich (dann kein CSRF-Header nötig).
**Zeiten:** ISO 8601 in UTC, Ausgabe mit `Z`. **Fehler:** JSON `{"detail": ...}`; `409` bei gleichzeitiger Änderung (`current_version` im Detail), `403` ohne Recht, `423` bei gesperrtem Konto, `429` bei Rate-Limit.
**Planungshinweise:** `POST/PATCH /api/shifts` antwortet mit `422` und `detail.warnings` (Ruhezeit < 11 h, Höchstarbeitszeit pro Tag/Woche, Vertragsstunden, Nichtverfügbarkeit). Ebenso `POST/PATCH /api/users` bei Stundenlohn unter Mindestlohn (`ignore_warnings: true` bestätigt). Mit `"ignore_warnings": true` wird trotzdem gespeichert (Audit-Eintrag `shift.warning_ignored`).
**Gleichzeitige Änderungen:** Änderbare Objekte (Schicht, Benutzer) tragen eine `version`; `PATCH` muss die zuletzt gesehene `version` mitsenden.

| Bereich | Wichtige Endpunkte |
|---|---|
| Anmeldung | `GET /api/auth/setup-status`, `POST /api/auth/register-tenant` (nur Ersteinrichtung), `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password`, `POST /api/auth/password-reset/request`, `POST /api/auth/password-reset/confirm` |
| Benutzer | `GET/POST /api/users`, `PATCH/DELETE /api/users/{id}`, `POST /api/users/{id}/lock\|unlock\|set-password`, `GET /api/users/{id}/export` |
| Rollen | `GET /api/roles`, `PUT /api/roles/{rolle}` |
| Abteilungen | `GET/POST /api/departments`, `PATCH/DELETE /api/departments/{id}` |
| Schichten | `GET /api/shifts?start&end`, `POST /api/shifts`, `PATCH/DELETE /api/shifts/{id}`, `POST /api/shifts/publish`, `POST /api/shifts/copy-week`, `POST /api/shifts/{id}/claim`, `GET /api/shifts/{id}/claims`, `POST /api/shifts/claims/{id}/decide` |
| Tausch | `GET/POST /api/swaps`, `POST /api/swaps/{id}/accept\|decide\|cancel` |
| Urlaub/Abwesenheit | `GET/POST /api/leave` (Feld `kind`: vacation, sick, special, wish), `GET /api/leave/balance`, `POST /api/leave/{id}/decide\|cancel`, `GET /api/leave/absences?start&end` (Kollegen sehen nur „absent“, nie den Grund) |
| Schichtvorlagen | `GET/POST /api/shift-templates`, `PATCH/DELETE /api/shift-templates/{id}` |
| Dokumente | `GET /api/documents`, `POST /api/documents?filename&title&category&user_id` (Datei als roher Request-Body), `GET /api/documents/{id}/download`, `DELETE /api/documents/{id}` |
| Verfügbarkeit | `GET /api/availability[?user_id]` (fremde nur Administrator und Planer-Rolle bzw. Recht `availability.manage`), `GET /api/availability/all` (ebenso), `PUT /api/availability[?user_id]` (ersetzt die eigene Liste; fremde nur mit `availability.manage`, wird protokolliert). Einträge: `weekday` (wöchentlich) **oder** `on_date` (nur dieser Tag) |
| Lohn | `GET /api/users/{id}/wages` (Stundensatz-Verlauf; `PATCH /api/users/{id}` mit `hourly_rate` und optional `rate_valid_from`), Benutzerfelder `weekly_hours`, `is_minor`, `is_minijob`, `work_days` |
| Personalakte | `GET /api/personnel/{id}` (Stamm-, Vertrags-, Lohn-, Urlaubs-, Arbeitszeitdaten, Dokumente nur mit `documents.manage`, Verlauf; Abruf wird protokolliert), `PUT /api/personnel/{id}` (Telefon, Funktion, Eintritt, Vertragsende, interne Notiz) – beides nur mit `users.manage` |
| Firma | `GET /api/auth/company` (Firmenname, Datenschutz-Ansprechpartner) |
| Zeit | `GET /api/time/status`, `POST /api/time/clock-in\|clock-out`, `GET /api/time/entries`, `PATCH /api/time/entries/{id}` |
| Berichte | `GET /api/reports/summary` (Zeilen enthalten u. a. `contract_hours`, `gross_cost`, `surcharge_cost`, `night_hours`, `avg_weekly_hours_26w`, `over_limit_days`, `minijob_months_over`), `GET /api/reports/payroll.csv` |
| Chat/Push | `GET/POST /api/messages`, `GET /api/push/public-key`, `POST /api/push/subscribe` |
| Admin | `GET /api/admin/audit\|system\|logs\|settings`, `PUT /api/admin/settings`, `GET/POST /api/admin/backups`, `GET /api/admin/backups/{name}` |
| System | `GET /api/health` (ohne Anmeldung), `WS /api/ws` (Echtzeit-Ereignisse) |

**WebSocket-Ereignisse** (`{"event": "...", "data": {...}}`): `shifts.changed`, `swaps.changed`, `leave.changed`, `time.changed`, `users.changed`, `chat.message`, `notification`. Sie sagen dem Client nur, *dass* er neu laden soll – Daten werden immer über die geprüfte REST-API abgerufen.
