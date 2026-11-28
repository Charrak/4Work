FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# postgresql-client (Version 15) passt zum Datenbank-Image postgres:15 (pg_dump/pg_restore für Backups)
# apt-get upgrade: Sicherheitsupdates des Basis-Images einspielen (Trivy-Prüfung in der CI)
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt requirements.lock* ./
# Mit requirements.lock (./scripts/lock-deps.sh) werden exakt festgelegte Versionen mit Prüfsummen installiert
RUN if [ -f requirements.lock ]; then pip install --no-cache-dir --require-hashes -r requirements.lock; \
    else echo "WARNUNG: requirements.lock fehlt - Abhaengigkeiten sind nicht fixiert" && pip install --no-cache-dir -r requirements.txt; fi
COPY app app
COPY migrations migrations
COPY alembic.ini entrypoint.sh ./
RUN chmod +x entrypoint.sh \
    && useradd --system --uid 10001 dienstplan \
    && mkdir -p /data/backups /data/logs /data/documents && chown -R dienstplan /data
USER dienstplan
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["./entrypoint.sh"]
