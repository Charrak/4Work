import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="dienstplan-test-")
os.environ.update({
    "ENV": "test",
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
    "COOKIE_SECURE": "false",
    "RATE_LIMIT_ENABLED": "false",
    "BACKUP_DIR": f"{_tmp}/backups",
    "LOG_DIR": f"{_tmp}/logs",
    "DOCUMENTS_DIR": f"{_tmp}/documents",
    "AUTO_CREATE_TABLES": "true",
    "DOCUMENTS_KEY": "dGVzdC1zY2hsdWVzc2VsLTMyLWJ5dGVzLWxhbmctISE=",
    "BACKUP_PASSPHRASE": "test-passphrase-mindestens-16-zeichen",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

PW = "Test-Passwort-123"


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def login(c: TestClient, email: str, password: str = PW):
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = c.cookies.get("csrf_token")
    return r.json()


@pytest.fixture()
def world(client):
    """Firma mit Admin, Planer (mitarbeiter) und zwei Schichtmitarbeitern (benutzer)."""
    r = client.post("/api/auth/register-tenant", json={
        "company": "Test GmbH", "name": "Admin", "email": "admin@test.de", "password": PW})
    assert r.status_code == 201, r.text
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    dept = client.get("/api/departments").json()[0]["id"]
    ids = {}
    for email, name, role in [("planer@test.de", "Paul Planer", "mitarbeiter"),
                              ("anna@test.de", "Anna", "benutzer"),
                              ("ben@test.de", "Ben", "benutzer")]:
        r = client.post("/api/users", json={"email": email, "name": name, "password": PW,
                                           "role": role, "department_ids": [dept],
                                           "vacation_days": 10})
        assert r.status_code == 201, r.text
        ids[email.split("@")[0]] = r.json()["id"]

    def new_client(email):
        c = TestClient(app)
        login(c, email)
        return c

    return {"admin": client, "dept": dept, "ids": ids, "new_client": new_client}
