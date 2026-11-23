import re

from tests.conftest import PW, login


def test_audit_log_records_admin_actions(world):
    admin = world["admin"]
    admin.post("/api/shifts", json={"department_id": world["dept"], "start": "2030-01-07T08:00:00Z",
                                    "end": "2030-01-07T16:00:00Z"})
    actions = {a["action"] for a in admin.get("/api/admin/audit?limit=200").json()}
    assert {"tenant.create", "user.create", "shift.create"} <= actions


def test_backup_create_list_download(world):
    admin = world["admin"]
    r = admin.post("/api/admin/backups")
    assert r.status_code == 201, r.text
    name = r.json()["name"]
    assert re.match(r"^backup-\d{8}-\d{6}\.sqlite3\.enc$", name)
    assert name in [b["name"] for b in admin.get("/api/admin/backups").json()]
    dl = admin.get(f"/api/admin/backups/{name}")
    assert dl.status_code == 200 and dl.content[:15] == b"SQLite format 3"
    assert admin.get("/api/admin/backups/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert admin.get("/api/admin/backups/evil.sh").status_code == 404


def test_system_info_and_settings(world):
    admin = world["admin"]
    info = admin.get("/api/admin/system").json()
    assert info["stats"]["users_active"] == 4 and info["database"] == "sqlite"
    assert admin.put("/api/admin/settings", json={"values": {"company_name": "Neu GmbH"}}).status_code == 200
    assert admin.get("/api/admin/settings").json()["company_name"] == "Neu GmbH"
    assert admin.put("/api/admin/settings", json={"values": {"hack": "1"}}).status_code == 422


def test_gdpr_delete_anonymizes_and_export(world):
    admin, ids = world["admin"], world["ids"]
    anna = world["new_client"]("anna@test.de")
    anna.post("/api/messages", json={"text": "persönlich"})
    exp = anna.get(f"/api/users/{ids['anna']}/export").json()
    assert exp["profil"]["email"] == "anna@test.de" and exp["nachrichten"][0]["text"] == "persönlich"
    assert world["new_client"]("ben@test.de").get(f"/api/users/{ids['anna']}/export").status_code == 403
    assert admin.delete(f"/api/users/{ids['anna']}").status_code == 204
    assert all(u["id"] != ids["anna"] for u in admin.get("/api/users").json())
    assert anna.get("/api/auth/me").status_code == 401     # Sitzung beendet
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        u = db.get(User, ids["anna"])
        assert u.name == "Gelöschter Benutzer" and u.email.endswith("@invalid.local")


def test_lock_unlock_user(world):
    admin, ids = world["admin"], world["ids"]
    ben = world["new_client"]("ben@test.de")
    assert admin.post(f"/api/users/{ids['ben']}/lock").status_code == 200
    assert ben.get("/api/auth/me").status_code == 401
    assert ben.post("/api/auth/login", json={"email": "ben@test.de", "password": PW}).status_code == 403
    admin.post(f"/api/users/{ids['ben']}/unlock")
    login(ben, "ben@test.de")


def test_websocket_sync_between_devices(world):
    """Eine Änderung auf Gerät A (Planer) erreicht Gerät B (Admin) per WebSocket."""
    admin, dept = world["admin"], world["dept"]
    planer = world["new_client"]("planer@test.de")
    cookie = f"access_token={admin.cookies.get('access_token')}"
    with admin.websocket_connect("/api/ws", headers={"cookie": cookie}) as ws:
        r = planer.post("/api/shifts", json={"department_id": dept, "start": "2030-01-07T08:00:00Z",
                                             "end": "2030-01-07T16:00:00Z"})
        assert r.status_code == 201
        assert ws.receive_json()["event"] == "shifts.changed"


def test_websocket_rejects_anonymous(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws"):
            pass


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"
