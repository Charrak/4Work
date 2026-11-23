from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PW, login


def test_setup_and_register_closed_afterwards(client):
    assert client.get("/api/auth/setup-status").json()["setup_required"] is True
    body = {"company": "A GmbH", "name": "A", "email": "a@a.de", "password": PW}
    assert client.post("/api/auth/register-tenant", json=body).status_code == 201
    assert client.get("/api/auth/setup-status").json()["setup_required"] is False
    other = TestClient(app)
    body["email"] = "b@b.de"
    assert other.post("/api/auth/register-tenant", json=body).status_code == 403


def test_weak_password_rejected(client):
    r = client.post("/api/auth/register-tenant", json={
        "company": "A GmbH", "name": "A", "email": "a@a.de", "password": "kurz1"})
    assert r.status_code == 422


def test_login_me_and_wrong_password(world):
    anna = TestClient(app)
    assert anna.post("/api/auth/login", json={"email": "anna@test.de", "password": "falsch-falsch1"}).status_code == 401
    me = login(anna, "anna@test.de")
    assert me["role"] == "benutzer" and "shifts.manage" not in me["permissions"]
    assert anna.get("/api/auth/me").json()["email"] == "anna@test.de"


def test_lockout_after_failed_attempts(world):
    c = TestClient(app)
    for _ in range(5):
        assert c.post("/api/auth/login", json={"email": "ben@test.de", "password": "falsch-falsch1"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "ben@test.de", "password": PW})
    assert r.status_code == 423


def test_csrf_required_for_cookie_sessions(world):
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "planer@test.de", "password": PW})
    r = c.post("/api/departments", json={"name": "Bar"})  # ohne X-CSRF-Token
    assert r.status_code == 403
    c.headers["X-CSRF-Token"] = c.cookies.get("csrf_token")
    assert c.post("/api/departments", json={"name": "Bar"}).status_code == 201


def test_unauthenticated_is_401(client):
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/shifts?start=2030-01-01T00:00:00Z&end=2030-01-08T00:00:00Z").status_code == 401


def test_change_password_invalidates_other_sessions(world):
    a1, a2 = world["new_client"]("anna@test.de"), world["new_client"]("anna@test.de")
    r = a1.post("/api/auth/change-password", json={"current_password": PW, "new_password": "Neues-Passwort-456"})
    assert r.status_code == 200
    assert a2.get("/api/auth/me").status_code == 401   # alte Sitzung beendet
    assert a1.get("/api/auth/me").status_code == 200   # aktuelle Sitzung bleibt


def test_password_reset_flow(world, monkeypatch):
    sent = {}
    monkeypatch.setattr("app.routers.auth.send_mail", lambda to, subj, body: sent.update(to=to, body=body))
    c = TestClient(app)
    assert c.post("/api/auth/password-reset/request", json={"email": "anna@test.de"}).status_code == 202
    assert c.post("/api/auth/password-reset/request", json={"email": "gibtsnicht@test.de"}).status_code == 202
    token = sent["body"].split("token=")[1].split()[0]
    assert c.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "Brandneu-Passwort-9"}).status_code == 200
    assert c.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "Nochmal-Passwort-9"}).status_code == 400
    login(c, "anna@test.de", "Brandneu-Passwort-9")
