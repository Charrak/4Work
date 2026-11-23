import os
import re
import sqlite3
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from ..config import settings
from . import crypto

NAME_RE = re.compile(r"^backup-\d{8}-\d{6}\.(dump|sqlite3|files\.tar\.gz)(\.enc)?$")
KINDS = (".dump", ".sqlite3", ".files.tar.gz")


def backup_dir() -> Path:
    p = Path(settings.backup_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _seal(plain: Path) -> Path:
    """Verschlüsselt eine fertige Sicherung (AES-256-GCM, Schlüssel aus BACKUP_PASSPHRASE) und löscht das Original.
    Ohne Passphrase (nur Entwicklung/Test) bleibt die Datei unverschlüsselt und wird nur umbenannt."""
    final = plain.with_name(plain.name.removesuffix(".partial"))
    if not settings.backup_passphrase:
        plain.replace(final)
        return final
    final = final.with_name(final.name + ".enc")
    tmp = final.with_name(final.name + ".tmp")
    try:
        with open(plain, "rb") as src, open(tmp, "wb") as dst:
            crypto.encrypt_stream(src, dst, settings.backup_passphrase)
        os.chmod(tmp, 0o600)
        tmp.replace(final)
    finally:
        tmp.unlink(missing_ok=True)
        plain.unlink(missing_ok=True)   # Klartext nie stehen lassen
    return final


def create_backup() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    url = make_url(settings.database_url)
    backend = url.get_backend_name()
    if backend == "sqlite":
        partial = backup_dir() / f"backup-{ts}.sqlite3.partial"
        src = sqlite3.connect(url.database)
        dst = sqlite3.connect(partial)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    elif backend == "postgresql":
        partial = backup_dir() / f"backup-{ts}.dump.partial"
        env = os.environ.copy()
        env["PGPASSWORD"] = url.password or ""
        cmd = ["pg_dump", "-Fc", "-h", url.host or "localhost", "-p", str(url.port or 5432),
               "-U", url.username or "postgres", "-f", str(partial), url.database]
        try:
            subprocess.run(cmd, check=True, env=env, capture_output=True, timeout=900)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    else:
        raise RuntimeError(f"Backup für {backend} wird nicht unterstützt")
    os.chmod(partial, 0o600)
    target = _seal(partial)
    docs = Path(settings.documents_dir)
    if docs.is_dir() and any(docs.iterdir()):
        files_partial = backup_dir() / f"backup-{ts}.files.tar.gz.partial"
        with tarfile.open(files_partial, "w:gz") as tar:
            tar.add(docs, arcname="documents")
        os.chmod(files_partial, 0o600)
        _seal(files_partial)
    prune_backups()
    return target


def list_backups() -> list[dict]:
    items = []
    for f in sorted(backup_dir().iterdir(), reverse=True):
        if NAME_RE.match(f.name):
            st = f.stat()
            items.append({"name": f.name, "size_bytes": st.st_size,
                          "created_at": datetime.fromtimestamp(st.st_mtime, timezone.utc)
                          .replace(tzinfo=None)})
    return items


def backup_path(name: str):
    if not NAME_RE.match(name):
        return None
    p = backup_dir() / name
    return p if p.is_file() else None


def prune_backups() -> None:
    if settings.backup_keep <= 0:
        return
    for kind in KINDS:   # je Art getrennt; verschlüsselte und alte unverschlüsselte Dateien zählen gemeinsam
        files = sorted((f for f in backup_dir().iterdir() if NAME_RE.match(f.name)
                        and f.name.removesuffix(".enc").endswith(kind)), key=lambda f: f.name.removesuffix(".enc"))
        for f in files[:-settings.backup_keep]:
            f.unlink(missing_ok=True)
