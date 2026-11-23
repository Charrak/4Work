"""Konfiguration ausschließlich über Umgebungsvariablen (siehe .env.example)."""
import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    secret_key: str
    access_token_minutes: int
    cookie_secure: bool
    allow_registration: bool
    rate_limit_enabled: bool
    trust_proxy: bool
    allowed_origins: tuple
    backup_dir: str
    backup_keep: int
    log_dir: str
    app_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    vapid_private_key: str
    vapid_public_key: str
    vapid_subject: str
    auto_create_tables: bool
    documents_dir: str
    max_upload_mb: int
    trusted_proxies: tuple
    enable_api_docs: bool
    documents_key: str
    backup_passphrase: str
    version: str = "1.8.0"


def load_settings() -> Settings:
    env = os.environ.get("ENV", "development").strip().lower()
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        if env == "production":
            raise RuntimeError("SECRET_KEY muss in Produktion gesetzt sein (mind. 32 Zeichen).")
        secret = "dev-only-insecure-key-change-me-0123456789"
    if env == "production" and len(secret) < 32:
        raise RuntimeError("SECRET_KEY ist zu kurz (mind. 32 Zeichen).")
    docs_key = os.environ.get("DOCUMENTS_KEY", "").strip()
    passphrase = os.environ.get("BACKUP_PASSPHRASE", "")
    if env == "production":
        if not docs_key or not passphrase:
            raise RuntimeError("DOCUMENTS_KEY und BACKUP_PASSPHRASE müssen in Produktion gesetzt sein "
                               "(./scripts/update.sh erzeugt sie bei Bedarf automatisch).")
        if len(passphrase) < 16:
            raise RuntimeError("BACKUP_PASSPHRASE ist zu kurz (mind. 16 Zeichen).")
    origins = tuple(o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip())
    return Settings(
        env=env,
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./dienstplan.db"),
        secret_key=secret,
        access_token_minutes=int(os.environ.get("ACCESS_TOKEN_MINUTES", "720")),
        cookie_secure=_bool("COOKIE_SECURE", env == "production"),
        allow_registration=_bool("ALLOW_TENANT_REGISTRATION", False),
        rate_limit_enabled=_bool("RATE_LIMIT_ENABLED", True),
        trust_proxy=_bool("TRUST_PROXY", False),
        allowed_origins=origins,
        backup_dir=os.environ.get("BACKUP_DIR", "./backups"),
        backup_keep=int(os.environ.get("BACKUP_KEEP", "14")),
        log_dir=os.environ.get("LOG_DIR", "./logs"),
        app_url=os.environ.get("APP_URL", "http://localhost:8000").rstrip("/"),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        smtp_from=os.environ.get("SMTP_FROM", "dienstplan@localhost"),
        vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", ""),
        vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY", ""),
        vapid_subject=os.environ.get("VAPID_SUBJECT", "mailto:admin@localhost"),
        auto_create_tables=_bool("AUTO_CREATE_TABLES", env != "production"),
        documents_dir=os.environ.get("DOCUMENTS_DIR", "./documents"),
        max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "10")),
        trusted_proxies=tuple(c.strip() for c in os.environ.get(
            "TRUSTED_PROXIES", "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16").split(",") if c.strip()),
        enable_api_docs=_bool("ENABLE_API_DOCS", env != "production"),
        documents_key=docs_key,
        backup_passphrase=passphrase,
    )


settings = load_settings()
