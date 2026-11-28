"""Monatslohn statt Stundensatz."""
from datetime import date

from app.services.payroll import hourly_equivalent, salary_share

PW = "Test-Passwort-123"


def test_salary_share_counts_whole_months_and_prorates_rest():
    s = lambda d: 3000.0  # noqa: E731
    assert salary_share(s, date(2030, 1, 15), date(2030, 2, 15)) == 3000.0      # Abrechnung 15.–14.
    assert salary_share(s, date(2030, 2, 1), date(2030, 3, 1)) == 3000.0        # Kalendermonat
    assert salary_share(s, date(2030, 1, 15), date(2030, 3, 15)) == 6000.0      # zwei Monate
    assert abs(salary_share(s, date(2030, 4, 1), date(2030, 4, 16)) - 1500.0) < 0.01   # halber April (30 Tage)
    assert hourly_equivalent(3000, 40) == 17.31


def _new(admin, world, **kw):
    body = {"email": "gehalt@test.de", "name": "Gina Gehalt", "password": PW, "role": "benutzer",
            "department_ids": [world["dept"]], **kw}
    return admin.post("/api/users", json=body)


def test_monthly_salary_needs_weekly_hours_and_sets_equivalent_rate(world):
    admin = world["admin"]
    r = _new(admin, world, monthly_salary=3000)
    assert r.status_code == 422 and "Wochenstunden" in r.text
    r = _new(admin, world, monthly_salary=3000, weekly_hours=40)
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["monthly_salary"] == 3000 and u["hourly_rate"] == 17.31
    # Wochenstunden ändern → Satz wird neu berechnet
    u2 = admin.patch(f"/api/users/{u['id']}", json={"version": u["version"], "weekly_hours": 30}).json()
    assert u2["hourly_rate"] == hourly_equivalent(3000, 30) and u2["monthly_salary"] == 3000
    # zurück zum Stundenlohn
    u3 = admin.patch(f"/api/users/{u['id']}", json={"version": u2["version"], "monthly_salary": 0, "hourly_rate": 15}).json()
    assert u3["monthly_salary"] is None and u3["hourly_rate"] == 15


def test_monthly_salary_below_minimum_wage_warns(world):
    r = _new(world["admin"], world, monthly_salary=1000, weekly_hours=40)
    assert r.status_code == 422 and "Mindestlohn" in r.text


def test_report_uses_salary_not_hours(world):
    admin = world["admin"]
    u = _new(admin, world, monthly_salary=3000, weekly_hours=40, rate_valid_from="2030-01-01").json()
    # Zeitraum 15.01.–14.02.2030 in deutscher Zeit (Mitternacht MEZ = 23:00 UTC am Vortag)
    rep = admin.get("/api/reports/summary?start=2030-01-14T23:00:00Z&end=2030-02-14T23:00:00Z").json()
    row = next(r for r in rep["rows"] if r["user_id"] == u["id"])
    assert row["pay_type"] == "monthly" and row["labor_cost"] == 3000.0 and row["gross_cost"] == 3000.0
