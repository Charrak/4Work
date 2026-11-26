# Technische Entscheidungen, Grenzen und Teststatus

## Entscheidungen (und warum)
| Thema | Entscheidung |
|---|---|
| Einzelbetrieb | Genau eine Firma (Wunsch des Betreibers). Intern bleibt eine Firmen-ID in den Tabellen, damit die Datentrennung sauber ist; weitere Firmen sind per Voreinstellung gesperrt (`ALLOW_TENANT_REGISTRATION=false`). |
| Stack | FastAPI + SQLAlchemy 2 + PostgreSQL 15, React + TypeScript + Vite, Caddy (HTTPS), Docker Compose. PostgreSQL 15 passt zum `pg_dump` im Backend-Image. |
| Anmeldung | JWT im HttpOnly-Cookie + CSRF-Token; Sitzungen enden bei Passwortwechsel, Sperre, Rollenänderung. |
| Gleichzeitiges Arbeiten | Optimistische Sperre (`version`); Konflikte → HTTP 409, nichts wird überschrieben. |
| Synchronisierung | WebSocket sendet nur „neu laden“-Signale; Daten kommen immer über die geprüfte REST-API. |
| Zeiten | Speicherung in UTC, Anzeige in Ortszeit des Geräts. |
| Löschen | Anonymisierung statt hartem Löschen (Aufbewahrungspflichten); Schichten per Soft-Delete. |
| Offline | App-Shell und zuletzt gelesene Daten offline; Chat/Urlaub werden gequeued; **Stempeln nur online** (korrekte Serverzeit). |
| Wiederherstellung | bewusst per Skript, nicht per Klick (Schutz vor versehentlichem Überschreiben). |
| Ein Backend-Prozess | WebSocket-Hub und Rate-Limit im Arbeitsspeicher; für diese Teamgröße ausreichend. |

## Bekannte Grenzen
**Arbeitszeitrecht (Hinweise, keine Rechtsberatung)**
- Planung und Stempeln prüfen Ruhezeit (11 h), Höchstarbeitszeit pro Tag (Standard 10 h) und Woche (Standard 48 h; Kalenderwoche Mo–So), Vertragsstunden und Verfügbarkeit. Beim Planen sind es übergehbare Hinweise (Protokoll). Beim Stempeln wird nur gesperrt, wenn die Einstellung „Einstempeln sperren“ aktiv ist; sonst steht ein Protokolleintrag (`time.limit_warning`).
- Der Bericht zeigt zusätzlich den Durchschnitt der letzten 26 Wochen je Person (Ausgleichszeitraum § 3 ArbZG) und markiert Überschreitungen. Tages-Durchschnitt (8 h) und Tarif-Ausgleichszeiträume sind nicht abgebildet.
- Jugendliche (Kennzeichen in der Benutzerverwaltung): 8 h/Tag, 40 h/Woche, 12 h Ruhe, 5 Tage/Woche, 6–20 Uhr, verlängerte Mindestpausen; Wochenendarbeit wird nur als Hinweis „Ausnahmebranche prüfen“ gemeldet. Nicht abgebildet: Berufsschultage, Nachweis ärztlicher Untersuchungen, Urlaubsanspruch nach Alter, Sonderregeln einzelner Branchen. Das Geburtsdatum wird bewusst nicht gespeichert, das Kennzeichen muss manuell gepflegt werden (auch beim 18. Geburtstag!).
- Tarifregeln: Es gibt keine vorgefertigten Tarifverträge. Grenzwerte, Mindestlohn, Zuschlagssätze und Minijob-Grenze sind einstellbar; Tarifspezifisches (Stufen, Sonderzahlungen, Ausgleichszeiträume) bleibt außerhalb.
**Lohn**
- Stundensatz mit Verlauf („gilt ab“); Berichte nutzen den am Tag gültigen Satz. Zuschläge: Nacht (23–6 Uhr, zusätzlich), Sonntag/Feiertag (höherer Satz) – Prozentsätze Standard 0, nach Vertrag/Tarif eintragen. Steuerfreiheit der Zuschläge wird nicht geprüft.
- Minijob: Verdienstgrenze pro Kalendermonat, je Person einstellbar (leer = Firmenvorgabe, Standard 603 €, Stand 2026 – bitte prüfen), Prüfung im Bericht und als Hinweis beim Planen (Planung ohne Zuschläge). Gleitzone/Midijob und Jahresgrenzen bei unregelmäßigem Verdienst fehlen.
- **Keine Lohnabrechnung:** Lohnsteuer, Sozialversicherung, Netto, Lohnzettel und Meldungen werden nicht berechnet. Das erfordert zertifizierte Lohnsoftware bzw. das Lohnbüro; die CSV liefert Stunden, Zuschlagsstunden und Brutto-Vorbereitung dafür.
- Mindestlohn (Standard 13,90 €) und Minijob-Grenze ändern sich jährlich und müssen manuell nachgepflegt werden.
**Sonstiges**
- „Woche kopieren“ rechnet Wochengrenzen in UTC; Schichten, die lokal vor ca. 02:00 Uhr beginnen, können in die Nachbarwoche fallen.
- Urlaub: Arbeitstage je Person (Teilzeit), NRW-Feiertage; keine halben Tage, keine Wochenstunden-Modelle, Anträge über den Jahreswechsel zählen zum Startjahr.
- Überstunden = gearbeitet minus Soll der bereits beendeten Schichten; kein Überstundenkonto über Monate.
- Aufgaben (v1.9): Zuweisung an Person (Vorrang) oder Abteilung oder alle; bei Abteilung/alle gilt „wer zuerst abhakt“. Checklisten-Punkte (max. 30), optional Pflicht-Kommentar, Fälligkeit, Priorität. Fünf einzelne Rechte (`tasks.do/create/manage/stats/stats_people`). Standard: Schichtmitarbeiter nur `do`; Planer-Rolle `do/create/manage/stats`; Statistik pro Person nur Administrator. Fremde Aufgaben sind per 404 unsichtbar. Abhaken ist idempotent (Offline-Warteschlange). Wiederkehrende Aufgaben werden beim Abruf erzeugt (kein Hintergrunddienst), bis 30 Tage rückwirkend. Statistik zählt erledigt beim Erledigenden, offen beim Zugewiesenen; Abruf „pro Person“ wird protokolliert. Beschäftigtendatenschutz: Auswertung pro Person ist Leistungs-/Verhaltenskontrolle (ggf. Mitbestimmung des Betriebsrats, Information der Beschäftigten). Nicht enthalten: Foto-Nachweis, Aufgaben-Kommentare/Chat, Unteraufgaben-Fristen.
- Verfügbarkeit: wöchentlich oder einzelner Tag (Nichtverfügbarkeit), Angaben anderer sehen/pflegen nur Administrator und Rollen mit dem eigenen Recht `availability.manage` (Standard: Administrator und Planer-Rolle; normale Mitarbeiter nie; entziehbar). Ohne das Recht sieht man beim Einplanen nur den Hinweis, nicht den Grund. Änderungen für andere werden protokolliert. Es gibt keine positiven „Wunschzeiten“; Einmalwünsche über „Wunschfrei“. Nur Hinweis beim Planen, keine Sperre.
- Kein Rollen-/Rechte-Feintuning pro Abteilung.
- Push-Nachrichten optional (VAPID-Schlüssel); auf iOS nur bei installierter App.
- Dokumente und Backups sind verschlüsselt (AES-256-GCM), die laufende PostgreSQL-Datenbank nicht (Festplattenverschlüsselung des Servers empfohlen). Kein Virenscan. Die Schlüssel liegen in der `.env` auf dem Server: Wer den Server übernimmt, hat auch die Schlüssel – der Schutz gilt für gestohlene Backups/Platten, nicht für einen kompromittierten Server.
- Stempeln nur online (Serverzeit).
- Alembic: Baseline plus Migrationen 0002–0007 (v1.7: keine neuen Migrationen).

## Teststatus (ehrlich)
- Backend: ca. 40 automatisierte Tests (Anmeldung, Rechte, Mandantentrennung, Schichten, Konflikte, Tausch, Urlaub, Zeiten, Berichte, Backup, DSGVO, WebSocket) liegen unter `backend/tests/`. **Sie wurden in der Entwicklungsumgebung nicht ausgeführt** (kein Netzwerk für Paketinstallation). Erster Schritt nach Erhalt: `cd backend && pip install -r requirements-dev.txt && pytest -v`.
- Frontend: Typprüfung nur gegen Platzhalter-Typen; **kein echter Build, kein Browsertest**. Vitest-Tests (`src/dates.test.ts`, `src/api.test.ts`) sind geschrieben; die Datumstests habe ich zusätzlich mit einem Minimal-Runner in Node geprüft (7/7 grün), die API-Tests und Vitest selbst nie ausgeführt. Es gibt keine Komponenten- oder Ende-zu-Ende-Tests. Erster Schritt: `cd frontend && npm install && npm run typecheck && npm test && npm run build`.
- Docker, Caddy, Skripte: Syntax geprüft (`bash -n`, YAML), **nicht gegen einen echten Server ausgeführt**. Erster Schritt: Installation auf einem Testserver, danach `./scripts/smoke-test.sh`, `./scripts/backup.sh` und eine Probe-Wiederherstellung.
- Die Datei `.github/workflows/ci.yml` führt Backend-Tests und Frontend-Build bei jedem Push in GitHub automatisch aus.
- Nicht automatisiert prüfbar ohne echte Geräte: PWA-Installation auf Android/iOS/Windows/macOS, Push, Offline-Verhalten im Browser, Serverneustart.


## Autoplaner (v1.10)

- **Verfahren:** deterministisches Greedy in zeitlicher Reihenfolge; je Schicht erhält die Person mit der geringsten Auslastung (geplant / Ziel) die Schicht, sofern alle Regeln eingehalten werden. Nachvollziehbar und ohne Zufall; kein mathematischer Optimierer (kann in Einzelfällen eine lokal bessere Verteilung übersehen – der Planer korrigiert im Dienstplan).
- **Harte Sperren:** Vertragszeitraum, Arbeitstage (abschaltbar), genehmigter Urlaub, Verfügbarkeit, Überschneidung, Stundenbudget, Ruhezeit, Tages-/Wochenmaximum, Wochenstunden laut Vertrag, Jugendschutz, Minijob-Grenze (dieselben Regeln wie beim manuellen Planen, nur ohne „Trotzdem speichern“).
- **Abrechnungszeitraum:** Einstellung `period_start_day` (15). Soll anteilig bei Ein-/Austritt; Urlaub/Krank an Arbeitstagen zählt als erfüllt. Die bestehende Minijob-Warnung beim manuellen Planen prüft weiterhin den Kalendermonat; der Autoplaner zusätzlich den Abrechnungszeitraum. Welcher Zeitraum für die Minijob-Grenze maßgeblich ist, bitte mit der Lohnbuchhaltung/dem Steuerberater klären.
- **Datenschutz:** Der Planer sieht keine Begründungstexte der Verfügbarkeit (nur „nicht verfügbar“). Übernommene Schichten bleiben unveröffentlicht, bis ein Mensch sie freigibt (keine automatisierte Entscheidung ohne menschliche Prüfung).
- **Nicht enthalten:** Wünsche/Präferenzen (z. B. „lieber früh“), Qualifikationen je Schicht, Feiertagszuschläge im Vorschlag, Mindestbesetzung je Tageszeit als Dauerregel.
