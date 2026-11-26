"""Aufgaben und Checklisten: Rechte, Sichtbarkeit, Abhaken, Wiederholungen, Statistik."""
from datetime import datetime, timedelta, timezone

from app.utils import utcnow


def iso(dt):
    return dt.replace(tzinfo=timezone.utc).isoformat()


def mk(client, title="Aufgabe", **kw):
    r = client.post("/api/tasks", json={"title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def ids(rows):
    return {t["title"] for t in rows}


def test_permission_matrix(world):
    admin, planer = world["admin"], world["new_client"]("planer@test.de")
    anna = world["new_client"]("anna@test.de")
    # Schichtmitarbeiter: nur eigene Aufgaben sehen/abhaken
    assert anna.get("/api/tasks").status_code == 200
    assert anna.get("/api/tasks?scope=all").status_code == 403
    assert anna.post("/api/tasks", json={"title": "x"}).status_code == 403
    assert anna.get("/api/task-templates").status_code == 403
    assert anna.get("/api/tasks/stats?start=2030-01-01&end=2030-01-31").status_code == 403
    # Planer: anlegen, alle sehen, Vorlagen, Statistik – aber NICHT pro Person
    assert planer.post("/api/tasks", json={"title": "x"}).status_code == 201
    assert planer.get("/api/tasks?scope=all").status_code == 200
    assert planer.get("/api/task-templates").status_code == 200
    assert planer.get("/api/tasks/stats?start=2030-01-01&end=2030-01-31").status_code == 200
    assert planer.get("/api/tasks/stats?start=2030-01-01&end=2030-01-31&group_by=person").status_code == 403
    # Administrator darf alles
    assert admin.get("/api/tasks/stats?start=2030-01-01&end=2030-01-31&group_by=person").status_code == 200
    roles = admin.get("/api/roles").json()
    assert "tasks.stats_people" in roles["permissions"]
    assert "tasks.stats_people" not in roles["roles"]["mitarbeiter"]
    assert "tasks.do" in roles["roles"]["benutzer"] and "tasks.create" not in roles["roles"]["benutzer"]


def test_visibility_by_assignment_and_department(world):
    admin, ids_ = world["admin"], world["ids"]
    planer, anna, ben = (world["new_client"](f"{n}@test.de") for n in ("planer", "anna", "ben"))
    other = admin.post("/api/departments", json={"name": "Andere Abteilung"}).json()["id"]
    mk(planer, "A für Anna", assignee_id=ids_["anna"])
    mk(planer, "B für Ben", assignee_id=ids_["ben"])
    mk(planer, "C Abteilung", department_id=world["dept"])
    mk(planer, "D fremde Abteilung", department_id=other)
    mk(planer, "E alle")
    assert ids(anna.get("/api/tasks").json()) == {"A für Anna", "C Abteilung", "E alle"}
    assert ids(ben.get("/api/tasks").json()) == {"B für Ben", "C Abteilung", "E alle"}
    assert len(planer.get("/api/tasks?scope=all").json()) == 5
    # Fremde Aufgaben sind nicht abrufbar und nicht abhakbar (404, Existenz wird nicht verraten)
    tid_b = next(t["id"] for t in planer.get("/api/tasks?scope=all").json() if t["title"] == "B für Ben")
    assert anna.get(f"/api/tasks/{tid_b}").status_code == 404
    assert anna.post(f"/api/tasks/{tid_b}/complete", json={}).status_code == 404
    assert anna.delete(f"/api/tasks/{tid_b}").status_code == 404


def test_complete_rules_items_comment_idempotent_reopen(world):
    planer, anna, ben = (world["new_client"](f"{n}@test.de") for n in ("planer", "anna", "ben"))
    t = mk(planer, "Geräte reinigen", department_id=world["dept"], items=["Laufband", "Hanteln", " "],
           require_comment=True)
    assert [i["text"] for i in t["items"]] == ["Laufband", "Hanteln"]            # Leere Punkte entfallen
    tid = t["id"]
    assert anna.post(f"/api/tasks/{tid}/complete", json={"comment": "ok"}).status_code == 422   # Punkte offen
    r = anna.post(f"/api/tasks/{tid}/items/0", json={"done": True})
    assert r.status_code == 200 and r.json()["items"][0]["done"] and r.json()["items"][0]["by_name"] == "Anna"
    anna.post(f"/api/tasks/{tid}/items/1", json={"done": True})
    assert anna.post(f"/api/tasks/{tid}/items/9", json={"done": True}).status_code == 404
    assert anna.post(f"/api/tasks/{tid}/complete", json={}).status_code == 422                  # Kommentar fehlt
    r = anna.post(f"/api/tasks/{tid}/complete", json={"comment": "alles sauber"})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "done" and d["completed_by_name"] == "Anna" and d["completion_comment"] == "alles sauber"
    # Idempotent: Ben (gleiche Abteilung) überschreibt nichts, auch wenn seine gemerkte Aktion später ankommt
    again = ben.post(f"/api/tasks/{tid}/complete", json={"comment": "doppelt"})
    assert again.status_code == 200 and again.json()["completed_by_name"] == "Anna"
    assert anna.post(f"/api/tasks/{tid}/items/0", json={"done": False}).status_code == 409     # erledigt = gesperrt
    # Wieder öffnen: nur wer abgehakt hat – oder die Verwaltung
    assert ben.post(f"/api/tasks/{tid}/reopen").status_code == 403
    assert planer.post(f"/api/tasks/{tid}/reopen").json()["status"] == "open"
    anna.post(f"/api/tasks/{tid}/complete", json={"comment": "nochmal"})
    assert anna.post(f"/api/tasks/{tid}/reopen").json()["status"] == "open"


def test_edit_and_delete_rights_follow_permissions(world):
    admin, ids_ = world["admin"], world["ids"]
    planer, anna, ben = (world["new_client"](f"{n}@test.de") for n in ("planer", "anna", "ben"))
    t = mk(planer, "Vom Planer", assignee_id=ids_["anna"])
    # Anna darf nur abhaken: nicht bearbeiten, nicht löschen
    assert anna.patch(f"/api/tasks/{t['id']}", json={"title": "X", "version": t["version"]}).status_code == 403
    assert anna.delete(f"/api/tasks/{t['id']}").status_code == 403
    assert anna.get(f"/api/tasks/{t['id']}").json()["can_edit"] is False
    # Mit zusätzlichem Recht „anlegen“ darf sie eigene Aufgaben anlegen, zuweisen, bearbeiten und löschen – fremde nicht
    perms = admin.get("/api/roles").json()["roles"]["benutzer"]
    assert admin.put("/api/roles/benutzer", json={"permissions": perms + ["tasks.create"]}).status_code == 200
    own = mk(anna, "Eigene", assignee_id=ids_["ben"])
    assert own["can_edit"] is True
    r = anna.patch(f"/api/tasks/{own['id']}", json={"title": "Eigene neu", "version": own["version"], "assignee_id": ids_["ben"]})
    assert r.status_code == 200 and r.json()["title"] == "Eigene neu"
    assert ben.get("/api/tasks").json()[0]["title"] == "Eigene neu"
    assert anna.patch(f"/api/tasks/{t['id']}", json={"title": "X", "version": t["version"]}).status_code == 403
    assert anna.delete(f"/api/tasks/{own['id']}").status_code == 204
    assert ids(ben.get("/api/tasks").json()) == set()
    # Verwaltung darf alles
    assert planer.delete(f"/api/tasks/{t['id']}").status_code == 204
    assert admin.get("/api/tasks/%d" % t["id"]).status_code == 404                              # gelöscht
    log = admin.get("/api/admin/audit?limit=200").json()
    assert any(x["action"] == "task.delete" for x in log)


def test_optimistic_locking_and_validation(world):
    planer = world["new_client"]("planer@test.de")
    t = mk(planer, "Version")
    ok = planer.patch(f"/api/tasks/{t['id']}", json={"title": "Neu", "version": t["version"]})
    assert ok.status_code == 200
    assert planer.patch(f"/api/tasks/{t['id']}", json={"title": "Alt", "version": t["version"]}).status_code == 409
    assert planer.post("/api/tasks", json={"title": "   "}).status_code == 422
    assert planer.post("/api/tasks", json={"title": "x", "priority": 5}).status_code == 422
    assert planer.post("/api/tasks", json={"title": "x", "assignee_id": 99999}).status_code == 404
    assert planer.post("/api/tasks", json={"title": "x", "department_id": 99999}).status_code == 404


def test_recurring_templates_generate_without_duplicates_and_catch_up(world):
    from app.db import SessionLocal
    from app.models import Task, TaskTemplate
    from app.utils import to_local
    planer, anna = world["new_client"]("planer@test.de"), world["new_client"]("anna@test.de")
    r = planer.post("/api/task-templates", json={"title": "Studio öffnen", "weekdays": "0123456", "due_time": "08:00",
                                                  "department_id": world["dept"], "items": ["Licht", "Musik"]})
    assert r.status_code == 201, r.text
    assert planer.post("/api/task-templates", json={"title": "x", "weekdays": "77"}).status_code == 422
    assert planer.post("/api/task-templates", json={"title": "x", "due_time": "25:00"}).status_code == 422
    tid = r.json()["id"]
    assert [t["title"] for t in anna.get("/api/tasks").json()] == ["Studio öffnen"]
    assert len(anna.get("/api/tasks").json()) == 1                                              # keine Duplikate
    # Mehrere Tage nicht geöffnet: versäumte Aufgaben entstehen rückwirkend und sind überfällig
    today = to_local(utcnow()).date()
    with SessionLocal() as db:
        tpl = db.get(TaskTemplate, tid)
        tpl.start_date, tpl.last_generated = today - timedelta(days=3), None
        for t in db.query(Task).all():
            db.delete(t)
        db.commit()
    rows = anna.get("/api/tasks").json()
    assert len(rows) == 4
    assert sum(1 for t in rows if t["overdue"]) >= 3
    assert all(len(t["items"]) == 2 for t in rows)
    # Löschen der Vorlage lässt bestehende Aufgaben (Statistik) bestehen und erzeugt nichts Neues
    assert planer.delete(f"/api/task-templates/{tid}").status_code == 204
    assert len(anna.get("/api/tasks").json()) == 4
    # Deaktivierte Vorlage erzeugt nichts
    r = planer.post("/api/task-templates", json={"title": "Aus", "active": False})
    assert r.status_code == 201
    assert "Aus" not in ids(anna.get("/api/tasks").json())


def test_stats_counts_and_person_rights(world):
    admin, ids_ = world["admin"], world["ids"]
    planer, anna = world["new_client"]("planer@test.de"), world["new_client"]("anna@test.de")
    now = utcnow()
    mk(planer, "Pünktlich", assignee_id=ids_["anna"], department_id=world["dept"], due_at=iso(now + timedelta(hours=2)))
    mk(planer, "Verspätet", assignee_id=ids_["anna"], department_id=world["dept"], due_at=iso(now - timedelta(hours=2)))
    mk(planer, "Überfällig", assignee_id=ids_["ben"], department_id=world["dept"], due_at=iso(now - timedelta(hours=3)))
    mk(planer, "Offen", assignee_id=ids_["ben"], department_id=world["dept"], due_at=iso(now + timedelta(days=1)))
    by = {t["title"]: t["id"] for t in planer.get("/api/tasks?scope=all").json()}
    assert anna.post(f"/api/tasks/{by['Pünktlich']}/complete", json={}).status_code == 200
    assert anna.post(f"/api/tasks/{by['Verspätet']}/complete", json={}).status_code == 200
    today = now.date()
    q = f"start={today - timedelta(days=2)}&end={today + timedelta(days=3)}"
    s = planer.get(f"/api/tasks/stats?{q}").json()
    tot = s["totals"]
    assert (tot["total"], tot["done"], tot["on_time"], tot["late"], tot["overdue"], tot["open"]) == (4, 2, 1, 1, 1, 1)
    assert tot["done_rate"] == 0.5 and tot["on_time_rate"] == 0.5 and tot["avg_delay_min"] >= 119
    assert len(s["groups"]) == 1 and s["groups"][0]["total"] == 4                                 # eine Abteilungsgruppe
    assert sum(d["total"] for d in s["days"]) == 4
    t = planer.get(f"/api/tasks/stats?{q}&group_by=task").json()
    assert {g["key"] for g in t["groups"]} == {"Pünktlich", "Verspätet", "Überfällig", "Offen"}
    # Person: nur mit eigenem Recht; erledigt zählt beim Erledigenden, offen beim Zugewiesenen; Abruf wird protokolliert
    assert planer.get(f"/api/tasks/stats?{q}&group_by=person").status_code == 403
    p = admin.get(f"/api/tasks/stats?{q}&group_by=person").json()
    by_person = {g["key"]: g for g in p["groups"]}
    assert by_person["Anna"]["done"] == 2 and by_person["Ben"]["overdue"] == 1 and by_person["Ben"]["open"] == 1
    assert any(x["action"] == "task.stats_people" for x in admin.get("/api/admin/audit?limit=200").json())
    # Zeitraum-Validierung und CSV
    assert planer.get("/api/tasks/stats?start=2030-02-01&end=2030-01-01").status_code == 422
    assert planer.get("/api/tasks/stats?start=2020-01-01&end=2030-01-01").status_code == 422
    c = planer.get(f"/api/tasks/stats.csv?{q}")
    assert c.status_code == 200 and c.text.startswith("﻿Abteilung;Aufgaben;") and "Gesamt;4;2;1;1;1;1;50,0;50,0;" in c.text
    assert anna.get(f"/api/tasks/stats.csv?{q}").status_code == 403


def test_notifications_and_done_filter(world):
    planer, anna = world["new_client"]("planer@test.de"), world["new_client"]("anna@test.de")
    t = mk(planer, "Heute erledigt", assignee_id=world["ids"]["anna"])
    anna.post(f"/api/tasks/{t['id']}/complete", json={})
    assert ids(anna.get("/api/tasks").json()) == set()                                          # nur offene
    assert ids(anna.get("/api/tasks?status=done").json()) == {"Heute erledigt"}
    assert ids(anna.get("/api/tasks?status=all").json()) == {"Heute erledigt"}


def test_deleting_a_person_frees_their_open_tasks(world):
    admin, ids_ = world["admin"], world["ids"]
    planer, ben = world["new_client"]("planer@test.de"), world["new_client"]("ben@test.de")
    t = mk(planer, "Für Anna", assignee_id=ids_["anna"], department_id=world["dept"])
    assert ids(ben.get("/api/tasks").json()) == set()
    r = admin.delete(f"/api/users/{ids_['anna']}")
    assert r.status_code == 204, r.text
    assert ids(ben.get("/api/tasks").json()) == {"Für Anna"}                     # nun Abteilungsaufgabe
    assert planer.get(f"/api/tasks/{t['id']}").json()["assignee_id"] is None
