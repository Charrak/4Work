"""Autoplaner: Abrechnungszeitraum 15.–14., faire Verteilung, Verfügbarkeit, Urlaub, Stundenrahmen, Rechte."""
from datetime import date, timedelta

from app.services.autoplan import period_bounds, periods_between


def next_monday(offset=60):
    d = date.today() + timedelta(days=offset)
    return d + timedelta(days=(7 - d.weekday()) % 7)


def setup_hours(world, anna=20, ben=20):
    admin, ids = world["admin"], world["ids"]
    for name, h in (("anna", anna), ("ben", ben)):
        r = admin.patch(f"/api/users/{ids[name]}", json={"version": 1, "weekly_hours": h})
        assert r.status_code == 200, r.text


def plan(client, world, mon, apply=False, days=(0, 1, 2, 3, 4), count=1, **kw):
    body = {"department_id": world["dept"], "start": str(mon), "end": str(mon + timedelta(days=6)),
            "slots": [{"weekdays": list(days), "start_time": "08:00", "end_time": "12:00", "count": count}],
            "apply": apply, **kw}
    r = client.post("/api/autoplan", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def shifts_of(client, mon, days=8):
    r = client.get(f"/api/shifts?start={mon}T00:00:00Z&end={mon + timedelta(days=days)}T00:00:00Z")
    assert r.status_code == 200, r.text
    return r.json()


def test_period_bounds_15_to_14():
    assert period_bounds(date(2030, 3, 20), 15) == (date(2030, 3, 15), date(2030, 4, 14))
    assert period_bounds(date(2030, 3, 10), 15) == (date(2030, 2, 15), date(2030, 3, 14))
    assert period_bounds(date(2030, 12, 20), 15) == (date(2030, 12, 15), date(2031, 1, 14))
    assert period_bounds(date(2030, 1, 3), 15) == (date(2029, 12, 15), date(2030, 1, 14))
    assert period_bounds(date(2030, 3, 20), 1) == (date(2030, 3, 1), date(2030, 3, 31))
    assert periods_between(date(2030, 3, 10), date(2030, 3, 20), 15) == [
        (date(2030, 2, 15), date(2030, 3, 14)), (date(2030, 3, 15), date(2030, 4, 14))]


def test_preview_does_not_save_apply_is_idempotent_and_fair(world):
    admin = world["admin"]
    setup_hours(world)
    mon = next_monday()
    pre = plan(admin, world, mon)
    assert pre["applied"] is False and pre["counts"]["created"] == 5 and pre["counts"]["unfilled"] == 0
    assert all(r["shift_id"] is None for r in pre["created"])
    assert shifts_of(admin, mon) == []                      # Vorschau speichert nichts
    done = plan(admin, world, mon, apply=True)
    assert done["applied"] is True and done["counts"]["created"] == 5
    rows = shifts_of(admin, mon)
    assert len(rows) == 5 and all(not r["published"] for r in rows)
    per = {}
    for r in rows:
        per[r["user_id"]] = per.get(r["user_id"], 0) + 1
    assert set(per) == {world["ids"]["anna"], world["ids"]["ben"]} and abs(per[world["ids"]["anna"]] - per[world["ids"]["ben"]]) <= 1
    again = plan(admin, world, mon, apply=True)             # zweiter Lauf: Bedarf ist gedeckt
    assert again["counts"].get("created", 0) == 0 and len(shifts_of(admin, mon)) == 5
    assert any(a["action"] == "autoplan.apply" for a in admin.get("/api/admin/audit").json())


def test_availability_and_leave_are_respected(world):
    admin, ids = world["admin"], world["ids"]
    setup_hours(world)
    mon = next_monday()
    ben = world["new_client"]("ben@test.de")
    assert ben.put("/api/availability", json={"items": [{"weekday": 0, "start_time": "00:00", "end_time": "23:59"}]}).status_code == 200
    anna = world["new_client"]("anna@test.de")
    tue = mon + timedelta(days=1)
    r = anna.post("/api/leave", json={"start_date": str(tue), "end_date": str(tue), "kind": "vacation"})
    assert r.status_code == 201, r.text
    assert admin.post(f"/api/leave/{r.json()['id']}/decide", json={"approve": True}).status_code == 200
    plan(admin, world, mon, apply=True)
    by_day = {}
    for s in shifts_of(admin, mon):
        by_day[s["start"][:10]] = s["user_id"]
    assert len(by_day) == 5
    # Montag: Ben nicht verfügbar → Anna; Dienstag: Anna im Urlaub → Ben (Datum ist UTC, 08:00 Ortszeit = gleicher Tag)
    assert by_day[str(mon)] == ids["anna"] and by_day[str(tue)] == ids["ben"]


def test_unfilled_reasons_and_open_shifts(world):
    admin = world["admin"]
    setup_hours(world)
    mon = next_monday()
    ben = world["new_client"]("ben@test.de")
    ben.put("/api/availability", json={"items": [{"weekday": 0, "start_time": "00:00", "end_time": "23:59"}]})
    pre = plan(admin, world, mon, days=(0,), count=2)
    assert pre["counts"]["created"] == 1 and pre["counts"]["unfilled"] == 1
    assert pre["unfilled"][0]["reasons"].get("nicht verfügbar") == 1
    done = plan(admin, world, mon, apply=True, days=(0,), count=2, create_open=True)
    rows = shifts_of(admin, mon)
    assert len(rows) == 2 and sorted(r["user_id"] is None for r in rows) == [False, True]
    assert done["counts"]["open_created"] == 1
    # offene Schicht wird bei späterem Lauf befüllt, sobald jemand verfügbar ist (kein Duplikat)
    ben.put("/api/availability", json={"items": []})
    later = plan(admin, world, mon, apply=True, days=(0,), count=2)
    assert later["counts"]["filled_existing"] == 1 and len(shifts_of(admin, mon)) == 2
    assert all(r["user_id"] for r in shifts_of(admin, mon))


def test_weekly_contract_limits_distribution(world):
    admin = world["admin"]
    setup_hours(world, anna=4, ben=4)                       # je 4 h/Woche = eine 4-h-Schicht
    mon = next_monday()
    res = plan(admin, world, mon, days=(0, 1, 2))
    assert res["counts"]["created"] == 2 and res["counts"]["unfilled"] == 1
    assert "Wochenstunden laut Vertrag" in res["unfilled"][0]["reasons"]


def test_hours_overview_and_period_credit(world):
    admin, ids = world["admin"], world["ids"]
    setup_hours(world)
    mon = next_monday()
    anna = world["new_client"]("anna@test.de")
    r = anna.post("/api/leave", json={"start_date": str(mon + timedelta(days=1)), "end_date": str(mon + timedelta(days=1)), "kind": "vacation"})
    admin.post(f"/api/leave/{r.json()['id']}/decide", json={"approve": True})
    plan(admin, world, mon, apply=True, days=(0,))
    ps, pe = period_bounds(mon, 15)
    h = admin.get(f"/api/autoplan/hours?day={mon}&department_id={world['dept']}").json()
    assert (h["period_start"], h["period_end"]) == (ps.isoformat(), pe.isoformat())
    row = {p["user_id"]: p for p in h["people"]}[ids["anna"]]
    days = (pe - ps).days + 1
    assert row["soll_h"] == round(20 * days / 7, 2)
    assert row["urlaub_h"] == 4.0                           # 20 h / 5 Arbeitstage
    assert row["ziel_h"] == round(row["soll_h"] - 4.0, 2)
    assert row["max_h"] == row["ziel_h"] and row["gesamt_h"] in (0.0, 4.0)
    assert row["rest_h"] == round(row["max_h"] - row["gesamt_h"], 2)
    # mit Überstunden-Spielraum steigt das Maximum
    h2 = admin.get(f"/api/autoplan/hours?day={mon}&overtime_pct=10").json()
    assert {p["user_id"]: p for p in h2["people"]}[ids["anna"]]["max_h"] > row["max_h"]


def test_rights_and_validation(world):
    admin = world["admin"]
    anna, planer = world["new_client"]("anna@test.de"), world["new_client"]("planer@test.de")
    mon = next_monday()
    body = {"department_id": world["dept"], "start": str(mon), "end": str(mon),
            "slots": [{"weekdays": [0], "start_time": "08:00", "end_time": "12:00"}]}
    assert anna.post("/api/autoplan", json=body).status_code == 403
    assert anna.get("/api/autoplan/hours").status_code == 403
    assert planer.post("/api/autoplan", json=body).status_code == 200
    bad = dict(body, slots=[{"weekdays": [9], "start_time": "08:00", "end_time": "12:00"}])
    assert planer.post("/api/autoplan", json=bad).status_code == 422
    bad = dict(body, slots=[{"weekdays": [0]}])
    assert planer.post("/api/autoplan", json=bad).status_code == 422
    assert planer.post("/api/autoplan", json=dict(body, end=str(mon + timedelta(days=90)))).status_code == 422
    assert planer.post("/api/autoplan", json=dict(body, department_id=99999)).status_code == 404


def test_period_start_day_setting(world):
    admin = world["admin"]
    assert admin.put("/api/admin/settings", json={"values": {"period_start_day": "0"}}).status_code == 422
    assert admin.put("/api/admin/settings", json={"values": {"period_start_day": "abc"}}).status_code == 422
    assert admin.put("/api/admin/settings", json={"values": {"period_start_day": "1"}}).status_code == 200
    h = admin.get("/api/autoplan/hours?day=2030-03-20").json()
    assert (h["period_start"], h["period_end"]) == ("2030-03-01", "2030-03-31")
