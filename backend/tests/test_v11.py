from datetime import date, timedelta

from tests.conftest import PW


def next_weekday_after(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7 or 7)


def test_holidays_nrw():
    from app.holidays import easter, holidays_nrw, is_holiday
    assert easter(2026) == date(2026, 4, 5) and easter(2027) == date(2027, 3, 28)
    h = holidays_nrw(2026)
    assert date(2026, 4, 3) in h and date(2026, 6, 4) in h          # Karfreitag, Fronleichnam
    assert not is_holiday(date(2026, 1, 6))                          # Heilige Drei Könige: nicht NRW
    from app.utils import workdays
    assert workdays(date(2026, 12, 21), date(2026, 12, 27)) == 4     # Fr 25.12. ist Feiertag, Sa/So zählen nicht


def test_leave_excludes_holidays(world):
    anna = world["new_client"]("anna@test.de")
    # Woche mit Karfreitag + Ostermontag in einem künftigen Jahr: Mo-Fr = 5 Tage, minus 1 Feiertag (Fr) = 4
    from app.holidays import easter
    y = date.today().year + 2
    e = easter(y)
    fri, mon = e - timedelta(days=2), e - timedelta(days=6)
    r = anna.post("/api/leave", json={"start_date": str(mon), "end_date": str(fri)})
    assert r.status_code == 201 and r.json()["days"] == 4


def test_sick_leave_retroactive_and_not_deducted(world):
    anna, planer = world["new_client"]("anna@test.de"), world["new_client"]("planer@test.de")
    d = date.today() - timedelta(days=3)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    assert anna.post("/api/leave", json={"start_date": str(d), "end_date": str(d), "kind": "vacation"}).status_code == 422
    r = anna.post("/api/leave", json={"start_date": str(d), "end_date": str(d), "kind": "sick"})
    assert r.status_code == 201 and r.json()["kind"] == "sick"
    planer.post(f"/api/leave/{r.json()['id']}/decide", json={"approve": True})
    bal = anna.get(f"/api/leave/balance?year={d.year}").json()
    assert bal["used"] == 0 and bal["remaining"] == 10               # Krankheit zählt nicht als Urlaub


def test_absence_overview_hides_reason_from_colleagues(world):
    anna, ben, planer = (world["new_client"](x) for x in ("anna@test.de", "ben@test.de", "planer@test.de"))
    mon = next_weekday_after(date.today() + timedelta(days=30), 0)
    lid = anna.post("/api/leave", json={"start_date": str(mon), "end_date": str(mon), "kind": "special"}).json()["id"]
    planer.post(f"/api/leave/{lid}/decide", json={"approve": True})
    q = f"start={mon}&end={mon}"
    assert ben.get(f"/api/leave/absences?{q}").json()[0]["kind"] == "absent"     # kein Grund sichtbar
    assert planer.get(f"/api/leave/absences?{q}").json()[0]["kind"] == "special"
    assert anna.get(f"/api/leave/absences?{q}").json()[0]["kind"] == "special"


def test_break_reduces_hours_and_overtime(world):
    admin, planer = world["admin"], world["new_client"]("planer@test.de")
    r = admin.post("/api/shifts", json={"department_id": world["dept"], "user_id": world["ids"]["anna"],
                                        "start": "2020-01-06T08:00:00Z", "end": "2020-01-06T16:00:00Z",
                                        "break_minutes": 30})
    assert r.status_code == 201 and r.json()["break_minutes"] == 30
    rep = planer.get("/api/reports/summary?start=2020-01-01T00:00:00Z&end=2020-02-01T00:00:00Z").json()
    anna = next(x for x in rep["rows"] if x["name"] == "Anna")
    assert anna["planned_hours"] == 7.5 and anna["overtime_hours"] == -7.5      # vergangene Schicht: 7,5 h Soll, 0 h gearbeitet
    assert admin.post("/api/shifts", json={"department_id": world["dept"], "start": "2030-01-08T08:00:00Z",
                                           "end": "2030-01-08T16:00:00Z", "break_minutes": 999}).status_code == 422


def test_shift_templates_crud_and_validation(world):
    admin, anna = world["admin"], world["new_client"]("anna@test.de")
    body = {"name": "Frühschicht", "department_id": world["dept"], "start_time": "07:30", "end_time": "15:30", "break_minutes": 30}
    t = admin.post("/api/shift-templates", json=body)
    assert t.status_code == 201
    assert admin.post("/api/shift-templates", json={**body, "start_time": "25:00"}).status_code == 422
    assert [x["name"] for x in anna.get("/api/shift-templates").json()] == ["Frühschicht"]
    assert anna.post("/api/shift-templates", json=body).status_code == 403
    tid = t.json()["id"]
    assert admin.put(f"/api/shift-templates/{tid}", json={**body, "name": "Früh"}).json()["name"] == "Früh"
    assert admin.delete(f"/api/shift-templates/{tid}").status_code == 204


def upload(c, name, data, **params):
    from urllib.parse import urlencode
    return c.post(f"/api/documents?{urlencode({'filename': name, **params})}", content=data,
                  headers={"Content-Type": "application/octet-stream"})


def test_documents_access_rules(world):
    admin, anna, ben = world["admin"], world["new_client"]("anna@test.de"), world["new_client"]("ben@test.de")
    pdf = b"%PDF-1.4 test"
    r = upload(admin, "vertrag.pdf", pdf, category="vertrag", user_id=world["ids"]["anna"], title="Arbeitsvertrag")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert [d["id"] for d in anna.get("/api/documents").json()] == [doc["id"]]       # eigener Vertrag sichtbar
    assert ben.get("/api/documents").json() == []                                    # fremder nicht
    assert ben.get(f"/api/documents/{doc['id']}/download").status_code == 404
    dl = anna.get(f"/api/documents/{doc['id']}/download")
    assert dl.status_code == 200 and dl.content == pdf and "attachment" in dl.headers["content-disposition"]
    assert anna.delete(f"/api/documents/{doc['id']}").status_code == 403             # löschen nur Verwalter
    # Eigene Krankschreibung hochladen darf jeder; Verträge nicht
    assert upload(ben, "au.pdf", pdf, category="attest").status_code == 201
    assert upload(ben, "v.pdf", pdf, category="vertrag").status_code == 403
    assert len(anna.get("/api/documents").json()) == 1                               # Bens Attest bleibt privat
    assert len(admin.get("/api/documents").json()) == 2


def test_document_upload_validation(world):
    admin = world["admin"]
    assert upload(admin, "x.exe", b"MZ", category="allgemein").status_code == 422     # Typ nicht erlaubt
    assert upload(admin, "x.pdf", b"nicht-pdf", category="allgemein").status_code == 422   # Inhalt passt nicht
    assert upload(admin, "x.pdf", b"", category="allgemein").status_code == 422
    assert upload(admin, "a.pdf", b"%PDF", category="attest").status_code == 422     # Attest braucht Person
    from app.config import settings
    big = b"%PDF" + b"0" * (settings.max_upload_mb * 1024 * 1024)
    assert upload(admin, "big.pdf", big, category="allgemein").status_code == 413
    r = upload(admin, "../../etc/passwd.txt", b"hallo", category="allgemein")
    assert r.status_code == 201 and r.json()["filename"] == "passwd.txt"             # Pfadanteile entfernt


def test_delete_user_requires_confirmation_for_documents(world):
    admin, ids = world["admin"], world["ids"]
    upload(admin, "v.pdf", b"%PDF-1", category="vertrag", user_id=ids["anna"])
    assert admin.delete(f"/api/users/{ids['anna']}").status_code == 409
    assert admin.delete(f"/api/users/{ids['anna']}?delete_documents=true").status_code == 204
    assert admin.get("/api/documents").json() == []


def test_backup_includes_documents(world):
    admin = world["admin"]
    upload(admin, "f.pdf", b"%PDF-1", category="allgemein")
    name = admin.post("/api/admin/backups").json()["name"]
    names = [b["name"] for b in admin.get("/api/admin/backups").json()]
    assert name in names and any(n.endswith(".files.tar.gz.enc") for n in names)


def test_company_endpoint_and_privacy_setting(world):
    admin, anna = world["admin"], world["new_client"]("anna@test.de")
    admin.put("/api/admin/settings", json={"values": {"privacy_contact": "datenschutz@firma.de"}})
    c = anna.get("/api/auth/company").json()
    assert c["privacy_contact"] == "datenschutz@firma.de" and c["company_name"]


def test_new_permissions_exist_in_roles(world):
    roles = world["admin"].get("/api/roles").json()
    assert "documents.view" in roles["roles"]["benutzer"] and "documents.manage" not in roles["roles"]["benutzer"]



# ---------- v1.2: Teilzeit, Verfügbarkeit, Ruhezeit ----------
def _free_monday() -> date:
    """Ein Montag mind. 60 Tage in der Zukunft, dessen Woche (Mo–So) keinen Feiertag enthält."""
    from app.holidays import is_holiday
    d = date.today() + timedelta(days=60)
    d += timedelta(days=(7 - d.weekday()) % 7)
    while any(is_holiday(d + timedelta(days=i)) for i in range(7)):
        d += timedelta(days=7)
    return d


def _utc(d: date, hhmm: str) -> str:
    """Lokale Zeit (Europe/Berlin) -> UTC-ISO, unabhängig von Sommer-/Winterzeit."""
    from datetime import datetime, timezone
    from app.utils import local_tz
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=local_tz()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_part_time_work_days_count_only_own_days(world):
    admin = world["admin"]
    r = admin.patch(f"/api/users/{world['ids']['anna']}", json={"version": 1, "work_days": "135"})
    assert r.status_code == 200 and r.json()["work_days"] == "135"
    anna = world["new_client"]("anna@test.de")
    mon = _free_monday()
    r = anna.post("/api/leave", json={"start_date": str(mon), "end_date": str(mon + timedelta(days=6)), "kind": "vacation"})
    assert r.status_code == 201, r.text
    assert r.json()["days"] == 3                                   # Mo, Mi, Fr
    assert anna.get(f"/api/leave/balance?year={mon.year}").json()["pending"] == 3


def test_invalid_work_days_rejected(world):
    r = world["admin"].post("/api/users", json={"email": "x@test.de", "name": "X", "password": PW, "work_days": "89"})
    assert r.status_code == 422


def test_rest_time_warning_and_override(world):
    admin, dept, uid = world["admin"], world["dept"], world["ids"]["anna"]
    mon = _free_monday()
    base = {"department_id": dept, "user_id": uid}
    assert admin.post("/api/shifts", json={**base, "start": _utc(mon, "14:00"), "end": _utc(mon, "22:00")}).status_code == 201
    nxt = {**base, "start": _utc(mon + timedelta(days=1), "05:00"), "end": _utc(mon + timedelta(days=1), "11:00")}  # nur 7 h Ruhe
    r = admin.post("/api/shifts", json=nxt)
    assert r.status_code == 422 and "Ruhezeit" in r.json()["detail"]["message"]
    r = admin.post("/api/shifts", json={**nxt, "ignore_warnings": True})
    assert r.status_code == 201, r.text


def test_availability_warning_and_privacy(world):
    admin, dept, uid = world["admin"], world["dept"], world["ids"]["anna"]
    anna = world["new_client"]("anna@test.de")
    r = anna.put("/api/availability", json={"items": [{"weekday": 0, "start_time": "00:00", "end_time": "12:00", "note": "Kurs"}]})
    assert r.status_code == 200 and len(r.json()) == 1
    assert anna.put("/api/availability", json={"items": [{"weekday": 0, "start_time": "12:00", "end_time": "10:00"}]}).status_code == 422
    assert anna.get(f"/api/availability?user_id={world['ids']['ben']}").status_code == 403
    assert len(admin.get(f"/api/availability?user_id={uid}").json()) == 1
    mon = _free_monday()
    body = {"department_id": dept, "user_id": uid, "start": _utc(mon, "08:00"), "end": _utc(mon, "12:00")}
    r = admin.post("/api/shifts", json=body)
    assert r.status_code == 422 and "nicht verfügbar" in r.json()["detail"]["message"]
    body.update(start=_utc(mon, "14:00"), end=_utc(mon, "18:00"))
    assert admin.post("/api/shifts", json=body).status_code == 201


# ---------- v1.3: Mindestlohn, Höchstarbeitszeit, Vertragsstunden ----------
def test_minimum_wage_warning_and_override(world):
    admin = world["admin"]
    body = {"email": "azubi@test.de", "name": "Azubi", "password": PW, "hourly_rate": 9.0}
    r = admin.post("/api/users", json=body)
    assert r.status_code == 422 and "Mindestlohn" in r.json()["detail"]["message"]
    assert admin.post("/api/users", json={**body, "ignore_warnings": True}).status_code == 201
    assert admin.post("/api/users", json={**body, "email": "ok@test.de", "hourly_rate": 15.0}).status_code == 201
    # Grenzwert einstellbar
    assert admin.put("/api/admin/settings", json={"values": {"minimum_wage": "8,50"}}).status_code == 200
    assert admin.post("/api/users", json={**body, "email": "x2@test.de", "hourly_rate": 9.0}).status_code == 201
    assert admin.put("/api/admin/settings", json={"values": {"max_daily_hours": "abc"}}).status_code == 422


def test_weekly_max_and_contract_hours_warning(world):
    admin, dept, uid = world["admin"], world["dept"], world["ids"]["anna"]
    mon = _free_monday()

    def shift(day_offset, start="08:00", end="18:00", **kw):
        d = mon + timedelta(days=day_offset)
        return admin.post("/api/shifts", json={"department_id": dept, "user_id": uid, "start": _utc(d, start),
                                               "end": _utc(d, end), "break_minutes": 0, **kw})
    r = admin.patch(f"/api/users/{uid}", json={"version": 1, "weekly_hours": 20})
    assert r.status_code == 200 and r.json()["weekly_hours"] == 20
    assert shift(0, "08:00", "16:00").status_code == 201                       # 8 h, unter 20 h
    r = shift(1, "08:00", "16:00")
    assert r.status_code == 201                                                # 16 h
    r = shift(2, "08:00", "16:00")
    assert r.status_code == 422 and "Vertragsstunden" in r.json()["detail"]["message"]   # 24 h > 20 h
    # über 10 h am Tag
    r = shift(3, "06:00", "18:00")
    assert r.status_code == 422 and "Mehr als 10" in r.json()["detail"]["message"]
    # Wochenhöchstgrenze 48 h über Einstellung herabsetzen: 8+8 = 16 > 12
    assert admin.put("/api/admin/settings", json={"values": {"max_weekly_hours": "12"}}).status_code == 200
    r = shift(4, "08:00", "12:00", ignore_warnings=True)
    assert r.status_code == 201


def test_report_counts_hours_over_limit(world):
    from datetime import datetime
    from app.db import SessionLocal
    from app.models import TimeEntry
    admin, uid = world["admin"], world["ids"]["anna"]
    with SessionLocal() as db:
        from app.models import User
        t = db.get(User, uid).tenant_id
        db.add(TimeEntry(tenant_id=t, user_id=uid, clock_in=datetime(2020, 3, 2, 6, 0), clock_out=datetime(2020, 3, 2, 19, 0)))
        db.commit()
    rep = admin.get("/api/reports/summary?start=2020-03-01T00:00:00Z&end=2020-04-01T00:00:00Z").json()
    anna = next(r for r in rep["rows"] if r["name"] == "Anna")
    assert anna["over_limit_days"] == 1 and anna["over_limit_weeks"] == 0     # 13 h − 45 min Pause = 12,25 h > 10 h


# ---------- v1.4: Lohnverlauf, Zuschläge, Minijob, Jugendliche, Stempelsperre ----------
def _entry(uid, ci, co, approved=True):
    from app.db import SessionLocal
    from app.models import TimeEntry, User
    with SessionLocal() as db:
        t = db.get(User, uid).tenant_id
        db.add(TimeEntry(tenant_id=t, user_id=uid, clock_in=ci, clock_out=co, approved=approved))
        db.commit()


def test_wage_history_used_per_day(world):
    from datetime import datetime
    admin, uid = world["admin"], world["ids"]["anna"]
    r = admin.patch(f"/api/users/{uid}", json={"version": 1, "hourly_rate": 14.0, "rate_valid_from": "2020-01-01"})
    assert r.status_code == 200
    r = admin.patch(f"/api/users/{uid}", json={"version": r.json()["version"], "hourly_rate": 16.0, "rate_valid_from": "2020-02-01"})
    assert r.status_code == 200
    hist = admin.get(f"/api/users/{uid}/wages").json()
    assert [h["hourly_rate"] for h in hist] == [16.0, 14.0]
    # 4 h am 6.1.2020 (Montag, 14 €), 4 h am 3.2.2020 (Montag, 16 €), je ohne Pause (≤ 6 h)
    _entry(uid, datetime(2020, 1, 6, 8, 0), datetime(2020, 1, 6, 12, 0))
    _entry(uid, datetime(2020, 2, 3, 8, 0), datetime(2020, 2, 3, 12, 0))
    rep = admin.get("/api/reports/summary?start=2020-01-01T00:00:00Z&end=2020-03-01T00:00:00Z").json()
    anna = next(x for x in rep["rows"] if x["name"] == "Anna")
    assert anna["labor_cost"] == 4 * 14 + 4 * 16 and anna["surcharge_cost"] == 0


def test_surcharges_night_sunday_holiday(world):
    from datetime import datetime
    admin, uid = world["admin"], world["ids"]["anna"]
    admin.patch(f"/api/users/{uid}", json={"version": 1, "hourly_rate": 20.0, "rate_valid_from": "2019-01-01"})
    for k, v in {"surcharge_night_pct": "25", "surcharge_sunday_pct": "50", "surcharge_holiday_pct": "100"}.items():
        assert admin.put("/api/admin/settings", json={"values": {k: v}}).status_code == 200
    # Sonntag 5.1.2020, 10–14 Uhr lokal (09–13 UTC im Winter): 4 h × 20 € × 50 % = 40 €
    _entry(uid, datetime(2020, 1, 5, 9, 0), datetime(2020, 1, 5, 13, 0))
    # Feiertag 1.5.2020 (Fr), 10–14 Uhr lokal (08–12 UTC, Sommerzeit): 4 h × 20 € × 100 % = 80 €
    _entry(uid, datetime(2020, 5, 1, 8, 0), datetime(2020, 5, 1, 12, 0))
    # Montag 6.1.2020, 22–02 Uhr lokal (21–01 UTC): 3 h Nacht (23–02) × 20 € × 25 % = 15 €; 6 h?? nein 4 h brutto
    _entry(uid, datetime(2020, 1, 6, 21, 0), datetime(2020, 1, 7, 1, 0))
    rep = admin.get("/api/reports/summary?start=2020-01-01T00:00:00Z&end=2020-06-01T00:00:00Z").json()
    a = next(x for x in rep["rows"] if x["name"] == "Anna")
    assert a["sunday_hours"] == 4.0 and a["holiday_hours"] == 4.0 and a["night_hours"] == 3.0
    assert a["surcharge_cost"] == 40 + 80 + 15
    assert a["gross_cost"] == a["labor_cost"] + a["surcharge_cost"] == 12 * 20 + 135


def test_minijob_limit_in_report_and_planning(world):
    from datetime import datetime
    admin, uid, dept = world["admin"], world["ids"]["anna"], world["dept"]
    admin.patch(f"/api/users/{uid}", json={"version": 1, "hourly_rate": 15.0, "is_minijob": True, "rate_valid_from": "2019-01-01"})
    assert admin.put("/api/admin/settings", json={"values": {"minijob_limit": "100"}}).status_code == 200
    _entry(uid, datetime(2020, 1, 6, 8, 0), datetime(2020, 1, 6, 15, 0))      # 7 h − 30 min = 6,5 h × 15 € = 97,50 €
    _entry(uid, datetime(2020, 1, 7, 8, 0), datetime(2020, 1, 7, 10, 0))      # + 30 € → 127,50 € > 100 €
    rep = admin.get("/api/reports/summary?start=2020-01-01T00:00:00Z&end=2020-02-01T00:00:00Z").json()
    assert next(x for x in rep["rows"] if x["name"] == "Anna")["minijob_months_over"] == 1
    mon = _free_monday()
    r = admin.post("/api/shifts", json={"department_id": dept, "user_id": uid, "start": _utc(mon, "08:00"), "end": _utc(mon, "16:00")})
    assert r.status_code == 422 and "Minijob" in r.json()["detail"]["message"]    # 8 h × 15 € = 120 € > 100 €


def test_minor_rules(world):
    admin, uid, dept = world["admin"], world["ids"]["ben"], world["dept"]
    assert admin.patch(f"/api/users/{uid}", json={"version": 1, "is_minor": True}).json()["is_minor"] is True
    mon = _free_monday()
    r = admin.post("/api/shifts", json={"department_id": dept, "user_id": uid, "start": _utc(mon, "08:00"), "end": _utc(mon, "17:00"), "break_minutes": 0})
    assert r.status_code == 422 and "Mehr als 8" in r.json()["detail"]["message"]
    r = admin.post("/api/shifts", json={"department_id": dept, "user_id": uid, "start": _utc(mon, "13:00"), "end": _utc(mon, "21:00")})
    assert r.status_code == 422 and "6 und 20 Uhr" in r.json()["detail"]["message"]
    assert admin.post("/api/shifts", json={"department_id": dept, "user_id": uid, "start": _utc(mon, "09:00"), "end": _utc(mon, "15:00")}).status_code == 201


def test_clock_in_blocked_when_limit_reached_and_setting_on(world):
    from datetime import timedelta as td
    from app.utils import utcnow
    admin, uid = world["admin"], world["ids"]["anna"]
    anna = world["new_client"]("anna@test.de")
    now = utcnow()
    _entry(uid, now - td(hours=5), now - td(hours=1))                  # Ruhezeit seit dem Ausstempeln nur 1 h
    assert anna.post("/api/time/clock-in", json={}).status_code == 201   # Sperre aus: nur Protokolleintrag
    anna.post("/api/time/clock-out")
    assert admin.put("/api/admin/settings", json={"values": {"block_clock_over_limit": "1"}}).status_code == 200
    r = anna.post("/api/time/clock-in", json={})
    assert r.status_code == 422 and "Einstempeln nicht möglich" in r.json()["detail"]["message"]


def test_avg_26_weeks_flag(world):
    from datetime import timedelta as td
    from app.utils import utcnow
    admin, uid = world["admin"], world["ids"]["anna"]
    assert admin.put("/api/admin/settings", json={"values": {"max_weekly_hours": "1"}}).status_code == 200
    now = utcnow()
    _entry(uid, now - td(days=10, hours=10), now - td(days=10, hours=2))   # 8 h − 30 min = 7,5 h → Ø 0,29 h/Woche
    _entry(uid, now - td(days=9, hours=10), now - td(days=9, hours=2))
    _entry(uid, now - td(days=8, hours=10), now - td(days=8, hours=2))
    _entry(uid, now - td(days=7, hours=10), now - td(days=7, hours=2))     # 4 × 7,5 = 30 h / 26 = 1,15 h > 1 h
    s = (now - td(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"); e = (now + td(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rep = admin.get(f"/api/reports/summary?start={s}&end={e}").json()
    a = next(x for x in rep["rows"] if x["name"] == "Anna")
    assert a["avg_weekly_hours_26w"] == round(30 / 26, 2) and a["avg_over_limit"] is True


# ---------- Sicherheitsprüfung (Selbstprüfung): Rechteausweitung, Lohndaten ----------
def _grant(admin, perms):
    from app.permissions import DEFAULT_ROLE_PERMISSIONS
    r = admin.put("/api/roles/mitarbeiter", json={"permissions": sorted(set(DEFAULT_ROLE_PERMISSIONS["mitarbeiter"]) | set(perms))})
    assert r.status_code == 200, r.text


def test_user_manager_cannot_touch_admin_accounts(world):
    admin = world["admin"]
    admin_id = admin.get("/api/auth/me").json()["id"]
    _grant(admin, ["users.manage"])
    planer = world["new_client"]("planer@test.de")
    assert planer.post(f"/api/users/{admin_id}/set-password", json={"password": "Hacker-Pass-123"}).status_code == 403
    assert planer.post(f"/api/users/{admin_id}/lock").status_code == 403
    assert planer.delete(f"/api/users/{admin_id}").status_code == 403
    assert planer.post("/api/users", json={"email": "evil@test.de", "name": "E", "password": PW, "role": "admin"}).status_code == 403
    pid = world["ids"]["planer"]
    me = planer.get("/api/auth/me").json()
    assert planer.patch(f"/api/users/{pid}", json={"version": me["version"], "role": "admin"}).status_code == 403
    # normale Verwaltung funktioniert weiterhin
    assert planer.post("/api/users", json={"email": "neu@test.de", "name": "Neu", "password": PW, "role": "benutzer"}).status_code == 201


def test_role_manager_cannot_grant_permissions_they_lack(world):
    admin = world["admin"]
    _grant(admin, ["roles.manage"])
    planer = world["new_client"]("planer@test.de")
    r = planer.put("/api/roles/benutzer", json={"permissions": ["shifts.view", "settings.manage", "documents.manage"]})
    assert r.status_code == 403
    assert planer.put("/api/roles/benutzer", json={"permissions": ["shifts.view", "chat.use"]}).status_code == 200


def test_planner_does_not_see_wages_in_user_list(world):
    admin = world["admin"]
    admin.patch(f"/api/users/{world['ids']['anna']}", json={"version": 1, "hourly_rate": 18.5, "weekly_hours": 30})
    planer = world["new_client"]("planer@test.de")
    anna = next(u for u in planer.get("/api/users").json() if u["name"] == "Anna")
    assert anna["hourly_rate"] is None and anna["weekly_hours"] is None
    anna = next(u for u in admin.get("/api/users").json() if u["name"] == "Anna")
    assert anna["hourly_rate"] == 18.5


def test_individual_minijob_limit(world):
    from datetime import datetime
    admin, uid, dept = world["admin"], world["ids"]["anna"], world["dept"]
    r = admin.patch(f"/api/users/{uid}", json={"version": 1, "hourly_rate": 15.0, "is_minijob": True,
                                               "minijob_limit": 150, "rate_valid_from": "2019-01-01"})
    assert r.status_code == 200 and r.json()["minijob_limit"] == 150
    assert admin.put("/api/admin/settings", json={"values": {"minijob_limit": "100"}}).status_code == 200   # Firmenvorgabe niedriger
    _entry(uid, datetime(2020, 1, 6, 8, 0), datetime(2020, 1, 6, 15, 0))      # 6,5 h × 15 € = 97,50 €
    _entry(uid, datetime(2020, 1, 7, 8, 0), datetime(2020, 1, 7, 10, 0))      # + 30 € = 127,50 € (< 150 individuell)
    rep = admin.get("/api/reports/summary?start=2020-01-01T00:00:00Z&end=2020-02-01T00:00:00Z").json()
    a = next(x for x in rep["rows"] if x["name"] == "Anna")
    assert a["minijob_limit"] == 150 and a["minijob_months_over"] == 0
    mon = _free_monday()
    ok = admin.post("/api/shifts", json={"department_id": dept, "user_id": uid, "start": _utc(mon, "08:00"), "end": _utc(mon, "16:00")})
    assert ok.status_code == 201                                                # 120 € < 150 €
    r = admin.post("/api/shifts", json={"department_id": dept, "user_id": uid, "start": _utc(mon, "17:00"), "end": _utc(mon, "20:00")})
    assert r.status_code == 422 and "150.00" in r.json()["detail"]["message"]  # 120 € + 45 € = 165 € > 150 € (gleicher Monat)
    # Minijob abwählen löscht die persönliche Grenze
    v = admin.get("/api/users").json()
    me = next(x for x in v if x["name"] == "Anna")
    r = admin.patch(f"/api/users/{uid}", json={"version": me["version"], "is_minijob": False})
    assert r.json()["minijob_limit"] is None


# ---------- v1.6: Personalakte ----------
def test_personnel_file_access_and_update(world):
    admin, uid = world["admin"], world["ids"]["anna"]
    planer = world["new_client"]("planer@test.de")
    assert planer.get(f"/api/personnel/{uid}").status_code == 403                  # Planer ohne „Benutzer verwalten“
    admin.patch(f"/api/users/{uid}", json={"version": 1, "hourly_rate": 16.0, "weekly_hours": 20, "rate_valid_from": "2020-01-01"})
    # Dokument für die Person
    r = admin.post(f"/api/documents?filename=vertrag.pdf&title=Arbeitsvertrag&category=vertrag&user_id={uid}",
                   content=b"%PDF-1.4 test", headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 201, r.text
    f = admin.get(f"/api/personnel/{uid}").json()
    assert f["profile"]["name"] == "Anna" and f["contract"]["weekly_hours"] == 20 and f["contract"]["hourly_rate"] == 16.0
    assert [w["hourly_rate"] for w in f["wages"]] == [16.0] and f["documents"][0]["title"] == "Arbeitsvertrag"
    assert f["leave"]["entitlement"] == 10
    r = admin.put(f"/api/personnel/{uid}", json={"version": f["profile"]["version"], "phone": " 0241 123456 ", "job_title": "Physiotherapeutin",
                                                 "hire_date": "2024-04-01", "contract_end": "2023-01-01", "hr_note": "x"})
    assert r.status_code == 422                                                      # Vertragsende vor Eintritt
    r = admin.put(f"/api/personnel/{uid}", json={"version": f["profile"]["version"], "phone": " 0241 123456 ", "job_title": "Physiotherapeutin",
                                                 "hire_date": "2024-04-01", "hr_note": "Fortbildung MT geplant"})
    assert r.status_code == 200, r.text
    f2 = admin.get(f"/api/personnel/{uid}").json()
    assert f2["profile"]["phone"] == "0241 123456" and f2["profile"]["hire_date"] == "2024-04-01"
    assert any(h["action"] == "personnel.update" for h in f2["history"]) or any(h["action"] == "user.wage_change" for h in f2["history"])
    # veraltete Version → Konflikt
    assert admin.put(f"/api/personnel/{uid}", json={"version": f["profile"]["version"], "phone": "1"}).status_code in (409, 422)


def test_personnel_file_of_admin_hidden_from_user_manager(world):
    admin = world["admin"]
    admin_id = admin.get("/api/auth/me").json()["id"]
    _grant(admin, ["users.manage"])
    planer = world["new_client"]("planer@test.de")
    assert planer.get(f"/api/personnel/{admin_id}").status_code == 403
    r = planer.get(f"/api/personnel/{world['ids']['anna']}")
    assert r.status_code == 200 and r.json()["documents"] == []     # ohne „documents.manage“ keine Dokumente in der Akte


def test_personnel_data_removed_on_delete(world):
    admin, uid = world["admin"], world["ids"]["ben"]
    f = admin.get(f"/api/personnel/{uid}").json()
    admin.put(f"/api/personnel/{uid}", json={"version": f["profile"]["version"], "phone": "0241 1", "hr_note": "privat"})
    assert admin.delete(f"/api/users/{uid}").status_code == 204
    exp = admin.get(f"/api/users/{uid}/export")
    assert exp.status_code in (200, 404)
    if exp.status_code == 200:
        assert exp.json()["profil"]["telefon"] is None and exp.json()["profil"]["interne_notiz"] is None
