# Dienstplan – Frontend (Etappe 3)

React 18 + TypeScript + Vite, als installierbare PWA. Design in den Logo-Farben (Navy/Limegrün), hell/dunkel.

## Entwicklung
```bash
# Terminal 1: Backend (siehe ../backend/README.md)
cd ../backend && uvicorn app.main:app --reload
# Terminal 2: Frontend
npm install
npm run dev          # http://localhost:5173 (leitet /api und WebSocket an Port 8000 weiter)
npm run typecheck
```
Beim ersten Aufruf erscheint die **Ersteinrichtung** (Firma + Administrator), falls das Backend noch leer ist.

## Produktion
```bash
npm run build        # erzeugt dist/ (wird in Etappe 4 vom Reverse-Proxy ausgeliefert)
```
Der Service Worker (`public/sw.js`) wird nur im Produktions-Build registriert. Installation als App braucht **HTTPS** (oder localhost).
Der Webserver muss unbekannte Pfade auf `index.html` umleiten (SPA-Fallback) – die Caddy-Konfiguration in Etappe 4 tut das.

## Aufbau
- `src/pages/` Seiten: Login/Ersteinrichtung/Passwort-Reset, Start, Dienstplan, Tausch & offene Schichten, Urlaub, Zeit, Chat, Berichte, Verwaltung (8 Reiter), Profil
- `src/api.ts` Fetch-Wrapper (Cookie + CSRF, Fehlermeldungen auf Deutsch, Offline-Warteschlange)
- `src/live.ts` WebSocket mit automatischer Wiederverbindung → Daten laden sich auf allen Geräten selbst neu
- `public/sw.js` App-Shell offline, Lesezugriffe mit Cache-Fallback, Web-Push
- `public/manifest.webmanifest`, `public/icons/` App-Symbole (inkl. maskierbar)

## Offline-Verhalten
- Zuletzt geladene Pläne, Urlaub, Chat usw. bleiben lesbar; ein Hinweisbalken zeigt den Offline-Status.
- Chat-Nachrichten und Urlaubsanträge werden offline gemerkt und nach Wiederverbindung automatisch gesendet.
- **Stempeln geht bewusst nur online**, damit die Uhrzeit korrekt vom Server stammt.
- Beim Abmelden werden zwischengespeicherte Daten gelöscht.
