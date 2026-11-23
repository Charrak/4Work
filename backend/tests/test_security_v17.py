"""Tests zu Proxy-Vertrauen, Rate-Limit, Verschlüsselung (Backups/Dokumente) und API-Doku."""
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.netutil import resolve_client_ip
from app.services import crypto

TRUSTED = ["127.0.0.1/32", "172.16.0.0/12"]


# ---------- Client-IP hinter dem Reverse Proxy ----------
def test_x_forwarded_for_ignored_unless_trusted_proxy():
    assert resolve_client_ip("198.51.100.9", "6.6.6.6", True, TRUSTED) == "198.51.100.9"     # direkter Zugriff
    assert resolve_client_ip("172.18.0.5", "6.6.6.6", False, TRUSTED) == "172.18.0.5"        # TRUST_PROXY aus
    assert resolve_client_ip("172.18.0.5", "203.0.113.7", True, TRUSTED) == "203.0.113.7"


def test_spoofed_left_entries_are_never_used():
    assert resolve_client_ip("172.18.0.5", "1.2.3.4, 203.0.113.7", True, TRUSTED) == "203.0.113.7"
    assert resolve_client_ip("172.18.0.5", "garbage", True, TRUSTED) == "172.18.0.5"


# ---------- Rate-Limit ----------
def test_rate_limiter_blocks_and_sweeps(monkeypatch):
    from fastapi import HTTPException
    from app import ratelimit
    import dataclasses
    monkeypatch.setattr(ratelimit, "settings", dataclasses.replace(ratelimit.settings, rate_limit_enabled=True))
    rl = ratelimit.RateLimiter(3, 60)
    for _ in range(3):
        rl.hit("a")
    with pytest.raises(HTTPException) as e:
        rl.hit("a")
    assert e.value.status_code == 429
    rl.hit("b")                                   # anderer Schlüssel unabhängig
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 10)
    for i in range(50):
        rl.hit(f"k{i}")
    assert len(rl.hits) <= 11                      # Speicher bleibt begrenzt


def test_login_is_limited_per_account_across_ips(world, monkeypatch):
    import dataclasses
    from app import ratelimit
    monkeypatch.setattr(ratelimit, "settings", dataclasses.replace(ratelimit.settings, rate_limit_enabled=True))
    ratelimit.login_account_limiter.reset(); ratelimit.login_limiter.reset(); ratelimit.api_limiter.reset()
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    codes = [c.post("/api/auth/login", json={"email": "anna@test.de", "password": "falsch-falsch-1"}).status_code for _ in range(12)]
    assert 429 in codes
    for lim in (ratelimit.login_account_limiter, ratelimit.login_limiter, ratelimit.api_limiter):
        lim.reset()


# ---------- Verschlüsselung ----------
def test_documents_are_encrypted_on_disk_and_decrypted_on_download(world):
    from app.config import settings
    admin = world["admin"]
    secret = b"%PDF-1.4 streng geheimer Vertrag"
    r = admin.post(f"/api/documents?filename=v.pdf&title=Vertrag&category=vertrag&user_id={world['ids']['anna']}",
                   content=secret, headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 201, r.text
    files = [f for f in Path(settings.documents_dir).iterdir() if f.is_file()]
    assert files and all(secret not in f.read_bytes() and f.read_bytes().startswith(b"DPENC1") for f in files)
    dl = admin.get(f"/api/documents/{r.json()['id']}/download")
    assert dl.status_code == 200 and dl.content == secret
    assert "attachment" in dl.headers["content-disposition"] and dl.headers["x-content-type-options"] == "nosniff"


def test_legacy_plain_documents_are_still_served(world):
    from app.config import settings
    from app.db import SessionLocal
    from app.models import Document, User
    admin, uid = world["admin"], world["ids"]["anna"]
    plain = b"%PDF-1.4 alt und unverschluesselt"
    Path(settings.documents_dir).mkdir(parents=True, exist_ok=True)
    (Path(settings.documents_dir) / "legacyfile").write_bytes(plain)
    with SessionLocal() as db:
        d = Document(tenant_id=db.get(User, uid).tenant_id, user_id=uid, category="vertrag", title="alt", filename="alt.pdf",
                     content_type="application/pdf", size=len(plain), stored_name="legacyfile", uploaded_by=uid)
        db.add(d); db.commit(); did = d.id
    assert admin.get(f"/api/documents/{did}/download").content == plain


def test_backup_is_encrypted_and_restorable(world):
    from app.config import settings
    from app.services import backup
    admin = world["admin"]
    name = admin.post("/api/admin/backups").json()["name"]
    assert name.endswith(".enc")
    blob = (Path(settings.backup_dir) / name).read_bytes()
    assert blob.startswith(b"DPBK1") and b"SQLite format 3" not in blob and b"anna@test.de" not in blob
    out = io.BytesIO()
    crypto.decrypt_stream(io.BytesIO(blob), out, settings.backup_passphrase)
    assert out.getvalue().startswith(b"SQLite format 3") and b"anna@test.de" in out.getvalue()
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_stream(io.BytesIO(blob), io.BytesIO(), "falsche-passphrase-xxxx")
    assert not [f for f in Path(settings.backup_dir).iterdir() if f.name.endswith(".partial")]   # kein Klartext übrig
    assert name in [b["name"] for b in backup.list_backups()]


def test_cli_decrypt_backup_roundtrip(world, tmp_path):
    from app.config import settings
    admin = world["admin"]
    name = admin.post("/api/admin/backups").json()["name"]
    src = Path(settings.backup_dir) / name
    env = {**os.environ, "BACKUP_PASSPHRASE": settings.backup_passphrase}
    res = subprocess.run([sys.executable, "-m", "app.cli", "decrypt-backup"], stdin=open(src, "rb"),
                         capture_output=True, env=env, cwd=Path(__file__).resolve().parent.parent)
    assert res.returncode == 0 and res.stdout.startswith(b"SQLite format 3")
    env["BACKUP_PASSPHRASE"] = "falsch-falsch-falsch-1"
    bad = subprocess.run([sys.executable, "-m", "app.cli", "decrypt-backup"], stdin=open(src, "rb"),
                         capture_output=True, env=env, cwd=Path(__file__).resolve().parent.parent)
    assert bad.returncode == 1


# ---------- Produktion: Pflicht-Schlüssel, API-Doku aus ----------
def test_production_requires_keys_and_disables_docs(monkeypatch):
    from app.config import load_settings
    base = {"ENV": "production", "SECRET_KEY": "x" * 40}
    for k in ("DOCUMENTS_KEY", "BACKUP_PASSPHRASE", "ENABLE_API_DOCS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in base.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(RuntimeError):
        load_settings()
    monkeypatch.setenv("DOCUMENTS_KEY", crypto.generate_key())
    monkeypatch.setenv("BACKUP_PASSPHRASE", "kurz")
    with pytest.raises(RuntimeError):
        load_settings()
    monkeypatch.setenv("BACKUP_PASSPHRASE", "eine-lange-passphrase-123")
    s = load_settings()
    assert s.enable_api_docs is False
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    assert load_settings().enable_api_docs is True


def test_api_docs_reachable_in_test_env_but_flag_controls_routes():
    from app.main import app
    from app.config import settings
    assert (app.docs_url is not None) == settings.enable_api_docs
