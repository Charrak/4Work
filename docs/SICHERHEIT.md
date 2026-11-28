# Sicherheits-Selbstprüfung (Stand v1.4)

**Wichtig:** Das ist eine Durchsicht des Quellcodes durch den Entwickler, **kein unabhängiges Audit und kein Penetrationstest**. Nichts davon wurde gegen einen laufenden Server geprüft. Vor dem Betrieb mit echten Personaldaten empfehle ich einen unabhängigen Test (z. B. durch einen IT-Sicherheitsdienstleister) und das Durchgehen der Betreiber-Checkliste unten.

## Geprüft und in Ordnung (nach Quellcode)
- Passwörter nur als Argon2-Hash; Sitzung per JWT im HttpOnly-Cookie, bei Passwort-/Rollen-/Sperränderung ungültig (`token_version`).
- CSRF: Double-Submit-Token bei Cookie-Anmeldung (jetzt mit zeitkonstantem Vergleich).
- SQL: ausschließlich SQLAlchemy-ORM bzw. parametrisierte Abfragen. XSS: React-Escaping, CSP im Reverse Proxy.
- Mandantentrennung (tenant_id) in Abfragen; Tests dafür vorhanden.
- Passwort-Zurücksetzen antwortet immer gleich (keine Konten-Erkennung), Token nur als Hash gespeichert, 1 Stunde gültig, Rate Limit.
- Dokumente: Endungs-Whitelist, Magic-Byte-Prüfung, Größenlimit beim Lesen, zufällige Dateinamen (kein Path Traversal), Auslieferung als Download mit `nosniff`, Zugriffe protokolliert.

## Gefunden und behoben (v1.4)
1. **Rechteausweitung (hoch):** Wer „Benutzer verwalten“ hatte, konnte Administratoren anlegen/befördern, deren Passwort setzen (Kontoübernahme), sperren oder löschen. → Administratorkonten dürfen jetzt nur noch Administratoren verwalten.
2. **Rechteausweitung über Rollen (hoch):** Wer „Rollen verwalten“ hatte, konnte beliebige Rechte vergeben. → Nicht-Administratoren dürfen nur Rechte weitergeben, die sie selbst besitzen.
3. **Lohndaten (mittel):** Die Benutzerliste enthielt für alle mit „Benutzerliste ansehen“ (Standard: Planer) Stundensatz, Vertragsstunden, Jugend-/Minijob-Kennzeichen. → Nur noch mit „Benutzer verwalten“ sichtbar.
4. **Verfügbarkeiten** wurden beim Löschen/Anonymisieren einer Person nicht entfernt. → Werden jetzt gelöscht.
5. **Upload ohne Ratenbegrenzung** → Limit 30 Uploads / 5 Minuten pro IP.
6. CSRF-Vergleich nicht zeitkonstant → `hmac.compare_digest`.
Alle Punkte haben automatische Tests (`tests/test_v11.py`, Abschnitt „Sicherheitsprüfung“), die ich **nicht ausführen konnte**.

## Umgesetzt in v1.7 (Härtung)
- **Proxy-Vertrauen:** `X-Forwarded-For` wird nur noch ausgewertet, wenn `TRUST_PROXY=true` UND die direkte Verbindung aus `TRUSTED_PROXIES` kommt (Standard: lokale/Docker-Netze); die Kette wird von rechts gelesen, gefälschte linke Einträge zählen nie. Caddy ersetzt die Angabe durch die echte Adresse, uvicorn wertet sie nicht mehr selbst aus (`--no-proxy-headers`), das Backend ist nicht nach außen veröffentlicht.
- **Rate-Limit:** zusätzlich Limit je Konto beim Login (10 Versuche / 15 min, bremst verteilte Angriffe), allgemeine Obergrenze je IP (600 Aufrufe/min), Speicher begrenzt (Aufräumen, Höchstzahl Schlüssel).
- **Verschlüsselung:** Backups und Dokumente AES-256-GCM (siehe WARTUNG.md). Pflicht in Produktion: ohne `BACKUP_PASSPHRASE`/`DOCUMENTS_KEY` startet das Backend nicht.
- **Abhängigkeiten:** `./scripts/lock-deps.sh` erzeugt `requirements.lock` (mit Hashes) und `package-lock.json`; Docker-Images nutzen sie automatisch (`--require-hashes`, `npm ci`); CI bricht ohne Lock-Dateien ab und prüft mit pip-audit, npm audit und Trivy; Dependabot und ein wöchentlicher Audit-Lauf sind eingerichtet; lokal: `./scripts/audit-deps.sh`. **Die Lock-Dateien konnte ich ohne Internet nicht erzeugen – bitte einmal ausführen und einchecken.**
- **API-Dokumentation** (`/api/docs`, `/api/redoc`, `/api/openapi.json`) in Produktion standardmäßig aus.

## Gefunden und behoben (v1.7.1)
- Offline-Warteschlange: Einträge sind jetzt dem Benutzer zugeordnet. Nach Benutzerwechsel (z. B. nach abgelaufener Sitzung) werden fremde Einträge nie gesendet, sondern verworfen und gemeldet. Abmelden löscht die Warteschlange und zeigt, wie viele Aktionen verworfen wurden.

## Teststatus (ehrlich)
| Bereich | Status |
|---|---|
| Verschlüsselung (Manipulation, falsches Passwort, Abschneiden) | ausgeführt, bestanden |
| Client-IP-Logik (`netutil`) | umgesetzt und geprüft |
| Backend-Tests gesamt | noch nicht ausgeführt |
| `test_security_v17.py` | geschrieben, noch nicht ausgeführt |
| Frontend-Tests (`api.test.ts`, inkl. neuer Benutzerwechsel-Tests) | geschrieben, noch nicht ausgeführt |
| Abhängigkeiten | Lock-Dateien müssen noch mit `./scripts/lock-deps.sh` erzeugt und eingecheckt werden |
| Penetrationstest | unabhängiger Dienstleister erforderlich |

## Offen / Grenzen
- Rate Limit und WebSocket-Hub liegen im Arbeitsspeicher eines Prozesses (ein Worker vorgesehen; nach Neustart zurückgesetzt).
- Kein Virenscan für Uploads. Sensible Freitextfelder und Chat sind in der Datenbank verschlüsselt (v1.11); Namen, E-Mail und Zeiten nicht (Festplattenverschlüsselung nötig – bei Oracle Cloud standardmäßig aktiv). Schlüssel liegen in der `.env`.
- Kein 2-Faktor-Login; Kontosperre nach Fehlversuchen vorhanden.
- Abhängigkeiten wurden von mir nicht auf bekannte Schwachstellen geprüft (kein Netzwerk) – das übernimmt CI/`audit-deps.sh`, sobald die Lock-Dateien eingecheckt sind.
- Jugend- und Gesundheitsdaten (Atteste) sind besonders schützenswert: Zugriff auf Server und Backups beschränken.

## Betreiber-Checkliste
- [ ] Starkes Administratorpasswort, nur 1–2 Administratoren
- [ ] Server: nur Ports 80/443 (und SSH mit Schlüssel) offen, automatische Sicherheitsupdates
- [ ] Festplattenverschlüsselung, Backups außerhalb des Servers (verschlüsselt)
- [ ] `.env` nur für root lesbar (`chmod 600`)
- [ ] `BACKUP_PASSPHRASE` und `DOCUMENTS_KEY` außerhalb des Servers gesichert, Probe-Wiederherstellung gemacht
- [ ] `./scripts/lock-deps.sh` ausgeführt, Lock-Dateien eingecheckt, CI grün
- [ ] Unabhängigen Sicherheitstest beauftragen (siehe PENTEST.md)
