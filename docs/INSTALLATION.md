# Installation auf einem VPS oder eigenen Linux-Server

## Was Sie brauchen
- Einen Linux-Server mit Ubuntu 22.04/24.04 oder Debian 12 (1 CPU, 2 GB RAM, 20 GB Speicher genügen für ein Team dieser Größe)
- Root-Zugang (SSH)
- Eine **Domain** (z. B. `dienstplan.meinefirma.de`), deren A-Eintrag auf die Server-IP zeigt – nötig für HTTPS und damit für die App-Installation auf dem Handy
- Offene Ports **80** und **443**

## Schritt für Schritt
1. **Per SSH anmelden:** `ssh root@<server-ip>`
2. **Projekt auf den Server bringen**, z. B. vom eigenen Rechner:
   `scp dienstplan-projekt.zip root@<server-ip>:/opt/` und auf dem Server `cd /opt && apt-get install -y unzip && unzip dienstplan-projekt.zip && cd dienstplan`
   (oder per `git clone` aus Ihrem Repository).
3. **Installationsskript starten:** `sudo ./scripts/install.sh`
   Es fragt nach: Domain, Firmenname, Name/E-Mail/Passwort des Administrators (Passwort: mind. 10 Zeichen mit Buchstaben und Ziffern; **leer lassen = es wird ein Zufallspasswort erzeugt und einmalig am Ende angezeigt**).
   Es installiert Docker (falls nötig), erzeugt zufällige Schlüssel in der Datei `.env`, baut und startet alle Dienste und legt Firma und Administrator an.
4. **Funktionstest:** `./scripts/smoke-test.sh` – alle Zeilen sollten mit `ok` beginnen.
5. **Anmelden:** `https://<Ihre-Domain>` im Browser öffnen. Das Zertifikat holt der Server automatisch (Let's Encrypt).
6. **Firewall (empfohlen):** `ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable`
7. **Ersten Backup-Test machen:** `./scripts/backup.sh` und prüfen, dass in `data/backups/` eine `.dump`-Datei liegt.

Die Datei `.env` enthält Ihre Geheimnisse (Datenbank-Passwort, Schlüssel). Sicher aufbewahren, nie weitergeben, nicht in Git einchecken.

## Was automatisch passiert
- **Neustart nach Serverausfall/Reboot:** alle Dienste starten selbst (Docker-Neustartregel `unless-stopped`, Docker startet beim Booten).
- **Gesundheitsprüfungen:** Datenbank und Backend werden laufend geprüft; das Backend startet erst, wenn die Datenbank bereit ist. Zusätzlich prüft ein Cron-Eintrag (`/etc/cron.d/dienstplan`) alle 5 Minuten, ob die Seite antwortet, und startet die Dienste bei Bedarf neu.
- **Datenbank-Migrationen:** laufen bei jedem Start automatisch.
- **Tägliches Backup** um 02:00 Uhr nach `data/backups/` (die letzten 14 bleiben, einstellbar mit `BACKUP_KEEP`).
- **HTTPS-Zertifikat:** wird automatisch erneuert.

## Optional
**E-Mail-Versand (Passwort zurücksetzen):** in `.env` die `SMTP_*`-Werte eintragen, dann `docker compose up -d`.
Ohne E-Mail-Versand kann der Administrator Passwörter unter *Verwaltung → Benutzer → Passwort* neu setzen.

**Push-Benachrichtigungen:** `./scripts/generate-vapid.sh` ausführen. Mitarbeiter aktivieren sie im Profil.
(Auf dem iPhone funktionieren Push-Nachrichten nur, wenn die App zum Home-Bildschirm hinzugefügt wurde.)

**Testbetrieb ohne Domain:** Bei der Domain-Abfrage nichts eingeben → Zugriff per `http://<server-ip>` ohne HTTPS (nur zum Ausprobieren: Passwörter laufen unverschlüsselt, und die App lässt sich so nicht installieren). Oder `localhost` eingeben → HTTPS nur auf dem Server selbst (Browser warnt wegen des Zertifikats).

## App installieren
- **Android (Chrome):** Seite öffnen → Menü ⋮ → „App installieren“ (oder Button „App installieren“ im Profil).
- **iPhone/iPad (Safari):** Teilen-Symbol → „Zum Home-Bildschirm“.
- **Windows/macOS (Chrome/Edge):** Installations-Symbol in der Adressleiste.
- **Linux:** Chrome/Chromium/Edge wie oben, sonst normal im Browser nutzen.


## Schlüssel sichern (wichtig!)
Die Installation erzeugt in `.env` die Schlüssel `BACKUP_PASSPHRASE` (Backups) und `DOCUMENTS_KEY` (Dokumente) und weist darauf hin. Kopieren Sie diese beiden Zeilen **sofort** an einen sicheren Ort außerhalb des Servers (z. B. Passwortmanager). Ohne sie sind Backups und Dokumente nach einem Serverausfall nicht wiederherstellbar.

## Abhängigkeiten fixieren (einmalig, vor dem Produktivbetrieb)
Auf einem Rechner mit Internet und Docker: `./scripts/lock-deps.sh` ausführen und die erzeugten Dateien `backend/requirements.lock`, `backend/requirements-dev.lock` und `frontend/package-lock.json` einchecken. Danach installiert der Build exakt diese Versionen mit Prüfsummen. Schwachstellen prüft `./scripts/audit-deps.sh` (und automatisch die CI).
