# Wartung und Betrieb

Alle Befehle im Projektordner auf dem Server ausführen (z. B. `/opt/dienstplan`).

## Status und Protokolle
| Aufgabe | Befehl |
|---|---|
| Alles prüfen (Rückgabewert 0 = gut) | `./scripts/healthcheck.sh` |
| Dienste anzeigen | `docker compose ps` |
| Protokoll des Servers | `docker compose logs --tail=100 backend` |
| Protokoll live | `docker compose logs -f backend` |
| Anwendungs-Fehlerprotokoll | im Programm: *Verwaltung → Fehlerprotokoll* (Datei `data/logs/app.log`) |
| Aktionsprotokoll (wer hat was getan) | im Programm: *Verwaltung → Protokoll* |

**Überwachung:** Die Installation richtet in `/etc/cron.d/dienstplan` automatisch ein: alle 5 Minuten `./scripts/healthcheck.sh` (antwortet die Seite nicht, werden die Dienste neu gestartet; Ausgabe in `data/logs/healthcheck.log`) und täglich 02:00 Uhr das Backup (`data/logs/backup.log`). Für eine E-Mail bei anhaltendem Ausfall `ALERT_EMAIL=…` in `.env` setzen und auf dem Server ein Mailprogramm (`mail`) einrichten. Alternativ von einem Dienst wie Uptime-Kuma die Adresse `https://<Domain>/api/health` abfragen lassen.

## Backups
- **Automatisch:** täglich 02:00 Uhr, Ablage in `data/backups/`, die letzten 14 bleiben.
- **Sofort:** `./scripts/backup.sh` oder im Programm *Verwaltung → Backups → Backup jetzt erstellen*.
- **Außerhalb des Servers sichern (wichtig!):** `data/backups/` regelmäßig auf einen anderen Rechner/Speicher kopieren, z. B.
  `rsync -a root@<server>:/opt/dienstplan/data/backups/ ~/dienstplan-backups/`
  Ein Backup, das nur auf demselben Server liegt, schützt nicht vor Serverausfall.
- **Verschlüsselung:** Backups werden mit AES-256-GCM verschlüsselt (Dateiendung `.enc`; Schlüssel aus `BACKUP_PASSPHRASE` in `.env`). Gespeicherte Dokumente sind einzeln mit `DOCUMENTS_KEY` verschlüsselt. **`BACKUP_PASSPHRASE` und `DOCUMENTS_KEY` müssen zusätzlich außerhalb des Servers gesichert werden (z. B. Passwortmanager) – ohne sie sind Backups und Dokumente unwiederbringlich verloren.** `install.sh`/`update.sh` erzeugen die Schlüssel automatisch, wenn sie fehlen, und weisen darauf hin. Ältere unverschlüsselte Dokumente werden beim Update automatisch nachverschlüsselt (manuell: `docker compose exec backend python -m app.cli encrypt-documents`). Eine `.enc`-Sicherung von Hand entschlüsseln: `docker compose run --rm --no-deps -T backend python -m app.cli decrypt-backup < backup-….dump.enc > backup.dump`. Die Datenbank im laufenden Betrieb (PostgreSQL-Volume) ist dadurch nicht verschlüsselt – dafür Festplattenverschlüsselung des Servers nutzen.
- **Dokumente:** Hochgeladene Dokumente (Verträge, Atteste) liegen in `data/documents/`. Jedes Backup erzeugt zusätzlich `backup-<Zeit>.files.tar.gz` mit diesen Dateien; `restore.sh` spielt sie automatisch mit zurück (der bisherige Ordner bleibt als `data/documents.old` erhalten). Beide Dateien gemeinsam extern sichern.
- **Aufbewahrung:** Backups enthalten personenbezogene Daten – Zugriff beschränken und alte Kopien löschen.

## Wiederherstellung
```bash
ls data/backups/
./scripts/restore.sh data/backups/backup-20261123-020000.dump.enc
```
Das Skript fragt zur Sicherheit nach („JA“), erstellt zuerst ein Sicherheits-Backup des aktuellen Stands, hält die Dienste an, legt die Datenbank neu an, spielt das Backup ein und startet alles wieder. Danach `./scripts/smoke-test.sh`.
**Üben Sie die Wiederherstellung einmal auf einem Testserver**, bevor Sie sie im Ernstfall brauchen.

**Kompletter Serverumzug:** Projektordner (inkl. `.env`) auf den neuen Server kopieren, `./scripts/install.sh` ausführen (die vorhandene `.env` bleibt erhalten; beim Schritt „Administrator“ abbrechen mit Strg+C ist okay), dann das Backup mit `restore.sh` einspielen und die Domain umstellen.

## Updates
1. Neue Projektdateien bereitstellen (`git pull` oder Dateien ersetzen – `.env` und `data/` nicht überschreiben).
2. `./scripts/update.sh` – erstellt zuerst ein Backup, baut neu, startet neu, führt Migrationen aus und prüft die Gesundheit.
Betriebssystem-Updates: `apt-get update && apt-get upgrade -y`, danach bei Kernel-Updates `reboot` – alle Dienste starten von selbst.

## Typische Aufgaben
- **Passwort eines Benutzers neu setzen:** *Verwaltung → Benutzer → Passwort*.
- **Administrator hat Passwort vergessen:** auf dem Server
  `docker compose exec -e ADMIN_PASSWORD='NeuesPasswort123' backend python -m app.cli reset-password --email chef@meinefirma.de`
  (mind. 10 Zeichen mit Buchstaben und Ziffern). Alle alten Sitzungen werden beendet. Besser: von Anfang an **zwei Administratoren** anlegen.
- **Mitarbeiter verlässt die Firma:** *Verwaltung → Benutzer → Sperren* (Daten bleiben) oder *Löschen* (Anonymisierung, siehe DSGVO.md).
- **Abteilung umbenennen:** *Verwaltung → Abteilungen*.
- **Speicherplatz prüfen:** `df -h` und *Verwaltung → System*.

## Fehlersuche
| Problem | Vorgehen |
|---|---|
| Seite nicht erreichbar | `docker compose ps`; `docker compose logs --tail=50 web`; DNS der Domain und Ports 80/443 prüfen |
| Zertifikatsfehler | Domain zeigt nicht auf den Server oder Port 80/443 blockiert; `docker compose logs web` |
| „Server nicht erreichbar“ in der App | `docker compose logs --tail=100 backend`; `docker compose restart backend` |
| Backend startet nicht | meist Datenbank noch nicht bereit oder falsche `.env`; `docker compose logs backend` |
| E-Mails kommen nicht an | SMTP-Werte in `.env` prüfen; ohne SMTP steht der Reset-Link im Backend-Protokoll |
| Änderungen erscheinen nicht live auf anderen Geräten | Seite neu laden; Proxy/Firewall muss WebSocket erlauben (Caddy tut das) |
| Nach Update kaputt | `docker compose logs backend`; bei Datenproblemen `restore.sh` mit dem Update-Backup |

## Hinweise zur Skalierung
Das Backend läuft bewusst mit **einem** Prozess (WebSocket-Verteilung und Zugriffsbegrenzung liegen im Arbeitsspeicher). Für ein Team dieser Größe ist das reichlich; sollte die Firma stark wachsen, wäre ein gemeinsamer Zwischenspeicher (Redis) nötig.
