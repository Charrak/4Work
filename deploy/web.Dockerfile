FROM node:26-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else echo "WARNUNG: package-lock.json fehlt" && npm install --no-audit --no-fund; fi
COPY frontend/ ./
# Typprüfung: "npm run typecheck" (läuft in CI); das Image baut nur das Bundle, damit eine
# Typ-Warnung nie die Installation verhindert.
RUN npx vite build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
