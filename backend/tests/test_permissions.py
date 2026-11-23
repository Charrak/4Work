from tests.conftest import PW


def test_benutzer_cannot_manage(world):
    anna = world["new_client"]("anna@test.de")
    assert anna.get("/api/users").status_code == 403
    assert anna.post("/api/shifts", json={"department_id": world["dept"], "start": "2030-01-01T08:00:00Z",
                                         "end": "2030-01-01T16:00:00Z"}).status_code == 403
    assert anna.get("/api/admin/audit").status_code == 403
    assert anna.get("/api/admin/backups").status_code == 403
    assert anna.get("/api/roles").status_code == 403


def test_planer_can_plan_but_not_administer(world):
    planer = world["new_client"]("planer@test.de")
    assert planer.get("/api/users").status_code == 200
    assert planer.post("/api/shifts", json={"department_id": world["dept"], "start": "2030-01-01T08:00:00Z",
                                           "end": "2030-01-01T16:00:00Z"}).status_code == 201
    assert planer.post("/api/users", json={"email": "x@test.de", "name": "X", "password": PW}).status_code == 403
    assert planer.get("/api/admin/audit").status_code == 403


def test_roles_are_customizable(world):
    admin = world["admin"]
    r = admin.put("/api/roles/benutzer", json={"permissions": ["shifts.view", "time.clock", "chat.use", "users.view"]})
    assert r.status_code == 200
    anna = world["new_client"]("anna@test.de")
    assert anna.get("/api/users").status_code == 200           # neu erlaubt
    assert anna.post("/api/leave", json={"start_date": "2030-03-04", "end_date": "2030-03-05"}).status_code == 403  # entzogen
    assert admin.put("/api/roles/admin", json={"permissions": []}).status_code == 400
    assert admin.put("/api/roles/benutzer", json={"permissions": ["gibt.es.nicht"]}).status_code == 422


def test_tenant_isolation(world):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal
    from app.services.tenants import create_tenant_with_admin
    with SessionLocal() as db:
        create_tenant_with_admin(db, "Andere GmbH", "boss@andere.de", "Boss", PW)
        db.commit()
    other = TestClient(app)
    other.post("/api/auth/login", json={"email": "boss@andere.de", "password": PW})
    other.headers["X-CSRF-Token"] = other.cookies.get("csrf_token")
    assert other.get("/api/users").json() and all(u["email"] == "boss@andere.de" for u in other.get("/api/users").json())
    assert other.patch(f"/api/users/{world['ids']['anna']}", json={"version": 1, "name": "Hack"}).status_code == 404


def test_cannot_remove_last_admin(world):
    admin = world["admin"]
    me = admin.get("/api/auth/me").json()
    r = admin.patch(f"/api/users/{me['id']}", json={"version": me["version"], "role": "benutzer"})
    assert r.status_code == 400
    assert admin.delete(f"/api/users/{me['id']}").status_code == 400
