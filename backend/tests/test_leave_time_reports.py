from datetime import date, timedelta

from tests.conftest import PW


def future_monday(weeks=8):
    d = date.today() + timedelta(weeks=weeks)
    return d - timedelta(days=d.weekday())


def test_leave_request_balance_and_approval(world):
    anna, planer = world["new_client"]("anna@test.de"), world["new_client"]("planer@test.de")
    mon = future_monday()
    r = anna.post("/api/leave", json={"start_date": str(mon), "end_date": str(mon + timedelta(days=4))})
    assert r.status_code == 201 and r.json()["days"] == 5
    bal = anna.get(f"/api/leave/balance?year={mon.year}").json()
    assert bal["pending"] == 5 and bal["remaining"] == 5
    # überlappender Antrag und Überziehen des Kontos werden abgelehnt
    assert anna.post("/api/leave", json={"start_date": str(mon + timedelta(days=2)), "end_date": str(mon + timedelta(days=3))}).status_code == 409
    assert anna.post("/api/leave", json={"start_date": str(mon + timedelta(days=14)), "end_date": str(mon + timedelta(days=28))}).status_code == 409
    assert anna.post(f"/api/leave/{r.json()['id']}/decide", json={"approve": True}).status_code == 403
    d = planer.post(f"/api/leave/{r.json()['id']}/decide", json={"approve": True})
    assert d.status_code == 200 and d.json()["status"] == "approved"
    assert anna.get(f"/api/leave/balance?year={mon.year}").json()["used"] == 5


def test_no_shift_assignment_during_approved_leave(world):
    anna, planer = world["new_client"]("anna@test.de"), world["new_client"]("planer@test.de")
    mon = future_monday()
    lid = anna.post("/api/leave", json={"start_date": str(mon), "end_date": str(mon)}).json()["id"]
    planer.post(f"/api/leave/{lid}/decide", json={"approve": True})
    r = planer.post("/api/shifts", json={"department_id": world["dept"], "user_id": world["ids"]["anna"],
                                         "start": f"{mon}T08:00:00Z", "end": f"{mon}T16:00:00Z"})
    assert r.status_code == 409 and "Urlaub" in r.json()["detail"]


def test_clock_in_out_and_location_consent(world):
    anna, planer = world["new_client"]("anna@test.de"), world["new_client"]("planer@test.de")
    assert anna.post("/api/time/clock-out").status_code == 409
    e = anna.post("/api/time/clock-in", json={"consent_location": False, "lat": 50.1, "lon": 8.6})
    assert e.status_code == 201
    assert anna.post("/api/time/clock-in", json={}).status_code == 409
    assert anna.get("/api/time/status").json()["clocked_in"] is True
    out = anna.post("/api/time/clock-out").json()
    assert out["clock_out"] is not None and out["minutes"] >= 0
    from app.db import SessionLocal
    from app.models import TimeEntry
    with SessionLocal() as db:
        entry = db.get(TimeEntry, e.json()["id"])
        assert entry.lat is None and entry.lon is None          # ohne Zustimmung nichts gespeichert
    assert anna.patch(f"/api/time/entries/{out['id']}", json={"approved": True}).status_code == 403
    # ohne Schicht gestempelt = Abweichung → Freigabe nur mit Kontrollvermerk
    assert planer.patch(f"/api/time/entries/{out['id']}", json={"approved": True}).status_code == 422
    ok = planer.patch(f"/api/time/entries/{out['id']}", json={"approved": True, "note": "Vertretung, abgesprochen"})
    assert ok.json()["approved"] is True


def test_reports_and_payroll_csv(world):
    admin, planer = world["admin"], world["new_client"]("planer@test.de")
    admin.post("/api/shifts", json={"department_id": world["dept"], "user_id": world["ids"]["anna"],
                                    "start": "2030-01-07T08:00:00Z", "end": "2030-01-07T16:00:00Z"})
    rep = planer.get("/api/reports/summary?start=2030-01-01T00:00:00Z&end=2030-02-01T00:00:00Z").json()
    anna = next(r for r in rep["rows"] if r["name"] == "Anna")
    assert anna["planned_hours"] == 8.0 and rep["totals"]["planned_hours"] == 8.0
    csv = planer.get("/api/reports/payroll.csv?start=2030-01-01T00:00:00Z&end=2030-02-01T00:00:00Z")
    assert csv.status_code == 200 and "Anna;anna@test.de;0,00;8,00" in csv.text
    assert world["new_client"]("anna@test.de").get("/api/reports/summary?start=2030-01-01T00:00:00Z&end=2030-02-01T00:00:00Z").status_code == 403


def test_chat(world):
    anna, ben = world["new_client"]("anna@test.de"), world["new_client"]("ben@test.de")
    assert anna.post("/api/messages", json={"text": "Hallo Team"}).status_code == 201
    msgs = ben.get("/api/messages").json()
    assert msgs[-1]["text"] == "Hallo Team" and msgs[-1]["user_name"] == "Anna"


def test_time_entry_correction_keeps_original_and_soft_delete(world):
    anna, planer = world["new_client"]("anna@test.de"), world["new_client"]("planer@test.de")
    e = anna.post("/api/time/clock-in", json={}).json()
    anna.post("/api/time/clock-out")
    r = planer.patch(f"/api/time/entries/{e['id']}",
                     json={"clock_in": "2030-01-07T08:00:00Z", "clock_out": "2030-01-07T16:00:00Z"}).json()
    assert r["clock_in"].startswith("2030-01-07T08:00") and r["orig_clock_in"] == e["clock_in"]
    assert r["orig_clock_out"] is not None and r["edited_by"]
    # zweite Korrektur überschreibt die Originalzeiten nicht
    r2 = planer.patch(f"/api/time/entries/{e['id']}", json={"clock_out": "2030-01-07T15:00:00Z"}).json()
    assert r2["orig_clock_in"] == e["clock_in"]
    # Löschen: nur mit Recht und Begründung, danach nicht mehr sichtbar
    assert anna.delete(f"/api/time/entries/{e['id']}?reason=Fehlstempelung").status_code == 403
    assert planer.delete(f"/api/time/entries/{e['id']}?reason=x").status_code == 422
    assert planer.delete(f"/api/time/entries/{e['id']}?reason=Fehlstempelung").status_code == 204
    left = planer.get("/api/time/entries?start=2030-01-01T00:00:00Z&end=2030-02-01T00:00:00Z&all=true").json()
    assert all(x["id"] != e["id"] for x in left)


def test_break_stamping(world):
    anna = world["new_client"]("anna@test.de")
    assert anna.post("/api/time/break-start").status_code == 409          # nicht eingestempelt
    anna.post("/api/time/clock-in", json={})
    assert anna.post("/api/time/break-end").status_code == 409            # keine Pause
    assert anna.post("/api/time/break-start").status_code == 200
    assert anna.post("/api/time/break-start").status_code == 409          # läuft schon
    assert anna.get("/api/time/status").json()["on_break"] is True
    out = anna.post("/api/time/clock-out").json()                         # beendet die Pause automatisch
    assert out["break_start"] is None and out["break_taken_min"] == 0


def test_effective_break_rules():
    from types import SimpleNamespace as N
    from app.routers.reports import effective_break
    assert effective_break(N(break_taken_min=10), 30, 8 * 60) == 30       # gestempelt < gesetzlich → gesetzlich
    assert effective_break(N(break_taken_min=50), 30, 8 * 60) == 50       # gestempelt länger → gestempelt
    assert effective_break(N(break_taken_min=None), 45, 8 * 60) == 45     # Schichtpause
    assert effective_break(N(break_taken_min=None), 0, 8 * 60) == 30      # 0 = gesetzlich
    assert effective_break(N(break_taken_min=None), None, 5 * 60) == 0    # ≤ 6 h keine Pause
