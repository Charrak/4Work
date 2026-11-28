from collections import defaultdict
from typing import Optional
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Shift, TimeEntry, User
from ..services.limits import get_limit
from ..services.common import permissions_for
from ..services.payroll import RateTable, SalaryTable, entry_pay, salary_share
from ..utils import UTCDateTime, csv_safe, to_local, utcnow

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _hours(a, b) -> float:
    return max(0.0, (b - a).total_seconds() / 3600)


def legal_break_minutes(duration_min: float, minor: bool = False) -> int:
    """Gesetzliche Mindestpause, falls keine Schicht mit eigener Pause zugeordnet ist.
    Erwachsene § 4 ArbZG (> 6 h: 30 min, > 9 h: 45 min); Jugendliche § 11 JArbSchG (> 4,5 h: 30 min, > 6 h: 60 min)."""
    if minor:
        return 60 if duration_min > 360 else 30 if duration_min > 270 else 0
    return 45 if duration_min > 540 else 30 if duration_min > 360 else 0


def effective_break(e, planned_break: Optional[int], gross_min: float, minor: bool = False) -> int:
    """Pause, die von der Anwesenheit abgezogen wird.
    1. Pause gestempelt → gestempelte Pause, mindestens aber die gesetzliche Mindestpause.
    2. sonst Pause der zugeordneten Schicht (0 = gesetzliche Mindestpause).
    3. sonst gesetzliche Mindestpause."""
    legal = legal_break_minutes(gross_min, minor)
    if getattr(e, "break_taken_min", None) is not None:
        return max(int(e.break_taken_min), legal)
    if planned_break:
        return int(planned_break)
    return legal


def compute_summary(db: Session, tenant_id: int, start, end) -> dict:
    now = utcnow()
    minijob_default = get_limit(db, tenant_id, "minijob_limit")
    users = db.scalars(select(User).where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
                       .order_by(User.name)).all()
    by_id = {u.id: u for u in users}
    rows = {u.id: {"user_id": u.id, "name": u.name, "email": u.email, "planned_hours": 0.0,
                   "planned_elapsed_hours": 0.0, "worked_hours": 0.0, "approved_hours": 0.0,
                   "contract_hours": round((u.weekly_hours or 0) * (end - start).total_seconds() / 604800, 2),
                   "overtime_hours": 0.0, "over_limit_days": 0, "over_limit_weeks": 0,
                   "avg_weekly_hours_26w": 0.0, "avg_over_limit": False,
                   "night_hours": 0.0, "sunday_hours": 0.0, "holiday_hours": 0.0,
                   "labor_cost": 0.0, "surcharge_cost": 0.0, "gross_cost": 0.0,
                   "is_minijob": bool(u.is_minijob), "minijob_limit": u.minijob_limit or minijob_default, "minijob_months_over": 0, "is_minor": bool(u.is_minor), "pay_type": "hourly"} for u in users}
    max_day, max_week = get_limit(db, tenant_id, "max_daily_hours"), get_limit(db, tenant_id, "max_weekly_hours")
    night_pct, sun_pct, hol_pct = (get_limit(db, tenant_id, k) for k in
                                   ("surcharge_night_pct", "surcharge_sunday_pct", "surcharge_holiday_pct"))
    rates = RateTable(db, tenant_id, {u.id: u.hourly_rate for u in users})
    salaries = SalaryTable(db, tenant_id, {u.id: u.monthly_salary for u in users})
    d0, d1 = to_local(start).date(), to_local(end).date()
    salaried = {u.id for u in users if salaries.is_salaried(u.id, d0, d1)}
    per_day: dict = defaultdict(float)
    per_week: dict = defaultdict(float)
    per_month: dict = defaultdict(float)
    shift_break: dict[int, int] = {}
    for s in db.scalars(select(Shift).where(Shift.tenant_id == tenant_id, Shift.deleted_at.is_(None),
                                            Shift.user_id.is_not(None), Shift.start >= start,
                                            Shift.start < end)).all():
        shift_break[s.id] = s.break_minutes
        if s.user_id in rows:
            net = max(0.0, _hours(s.start, s.end) - s.break_minutes / 60)
            rows[s.user_id]["planned_hours"] += net
            if s.end <= now:
                rows[s.user_id]["planned_elapsed_hours"] += net
    for e in db.scalars(select(TimeEntry).where(TimeEntry.tenant_id == tenant_id,
                                                TimeEntry.clock_out.is_not(None), TimeEntry.deleted_at.is_(None),
                                                TimeEntry.clock_in >= start, TimeEntry.clock_in < end)).all():
        r = rows.get(e.user_id)
        if r is None:
            continue
        gross_min = (e.clock_out - e.clock_in).total_seconds() / 60
        brk = effective_break(e, shift_break.get(e.shift_id) if e.shift_id else None, gross_min, r["is_minor"])
        h = max(0.0, gross_min - brk) / 60
        r["worked_hours"] += h
        if e.approved:
            r["approved_hours"] += h
        d = to_local(e.clock_in).date()
        per_day[(e.user_id, d)] += h
        per_week[(e.user_id, d - timedelta(days=d.weekday()))] += h
        base, sur, hn, hs, hh = entry_pay(e.user_id, e.clock_in, e.clock_out, h, rates, night_pct, sun_pct, hol_pct)
        if e.user_id in salaried:
            base = 0.0   # Festgehalt: Grundlohn kommt aus dem Monatslohn, nicht aus den Stunden
        r["labor_cost"] += base
        r["surcharge_cost"] += sur
        r["night_hours"] += hn
        r["sunday_hours"] += hs
        r["holiday_hours"] += hh
        per_month[(e.user_id, d.year, d.month)] += base + sur
    for uid in salaried:
        def sal_on(d, uid=uid):
            return salaries.salary(uid, d) or 0.0
        rows[uid]["labor_cost"] += salary_share(sal_on, d0, d1)
        rows[uid]["pay_type"] = "monthly"
        # Minijob-Grenze: Monatslohn zählt in jedem Kalendermonat des Zeitraums voll
        m = date(d0.year, d0.month, 1)
        while m < d1:
            per_month[(uid, m.year, m.month)] += sal_on(m)
            m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    day_lim = {uid: (8.0 if by_id[uid].is_minor else max_day) for uid in rows}
    week_lim = {uid: (40.0 if by_id[uid].is_minor else max_week) for uid in rows}
    for (uid, _), h in per_day.items():
        if h > day_lim[uid] + 1e-9:
            rows[uid]["over_limit_days"] += 1
    for (uid, _), h in per_week.items():
        if h > week_lim[uid] + 1e-9:
            rows[uid]["over_limit_weeks"] += 1
    for (uid, _y, _m), money in per_month.items():
        if rows[uid]["is_minijob"] and money > rows[uid]["minijob_limit"] + 1e-9:
            rows[uid]["minijob_months_over"] += 1
    # Durchschnitt der letzten 26 Wochen vor dem Ende des Zeitraums (Ausgleichszeitraum § 3 ArbZG)
    win_end = min(end, now)
    win_start = win_end - timedelta(weeks=26)
    totals26: dict[int, float] = defaultdict(float)
    for e in db.scalars(select(TimeEntry).where(TimeEntry.tenant_id == tenant_id, TimeEntry.clock_out.is_not(None),
                                                TimeEntry.deleted_at.is_(None),
                                                TimeEntry.clock_in >= win_start, TimeEntry.clock_in < win_end)).all():
        u = by_id.get(e.user_id)
        if not u:
            continue
        gm = (e.clock_out - e.clock_in).total_seconds() / 60
        brk = shift_break.get(e.shift_id) if e.shift_id in shift_break else None
        if brk is None:
            brk = legal_break_minutes(gm, bool(u.is_minor))
        totals26[e.user_id] += max(0.0, gm - brk) / 60
    for uid, tot in totals26.items():
        rows[uid]["avg_weekly_hours_26w"] = tot / 26
        rows[uid]["avg_over_limit"] = tot / 26 > week_lim[uid] + 1e-9
    for r in rows.values():
        r["overtime_hours"] = r["worked_hours"] - r["planned_elapsed_hours"]
        r["gross_cost"] = r["labor_cost"] + r["surcharge_cost"]
        for k in ("planned_hours", "planned_elapsed_hours", "worked_hours", "approved_hours", "overtime_hours",
                  "avg_weekly_hours_26w", "night_hours", "sunday_hours", "holiday_hours",
                  "labor_cost", "surcharge_cost", "gross_cost"):
            r[k] = round(r[k], 2)
    lst = list(rows.values())
    totals = {k: round(sum(r[k] for r in lst), 2) for k in
              ("planned_hours", "planned_elapsed_hours", "worked_hours", "approved_hours", "overtime_hours",
               "contract_hours", "over_limit_days", "over_limit_weeks", "night_hours", "sunday_hours",
               "holiday_hours", "labor_cost", "surcharge_cost", "gross_cost")}
    return {"start": start.isoformat() + "Z", "end": end.isoformat() + "Z", "rows": lst, "totals": totals}


# Geldbeträge sehen nur Personen mit „reports.wages“ (Datensparsamkeit, Art. 5 Abs. 1 lit. c DSGVO)
MONEY_KEYS = ("labor_cost", "surcharge_cost", "gross_cost", "minijob_limit")


def _wages_visible(db: Session, user: User) -> bool:
    return "reports.wages" in permissions_for(db, user)


def _validate(start, end):
    if end <= start or end - start > timedelta(days=370):
        raise HTTPException(422, "Zeitraum ungültig (maximal 370 Tage)")


@router.get("/summary")
def summary(start: UTCDateTime, end: UTCDateTime, user: User = Depends(require("reports.view")),
            db: Session = Depends(get_db)):
    _validate(start, end)
    data = compute_summary(db, user.tenant_id, start, end)
    data["wages_visible"] = _wages_visible(db, user)
    if not data["wages_visible"]:
        for r in [*data["rows"], data["totals"]]:
            for k in MONEY_KEYS:
                if k in r:
                    r[k] = None
    return data


@router.get("/payroll.csv")
def payroll_csv(start: UTCDateTime, end: UTCDateTime, user: User = Depends(require("reports.view")),
                db: Session = Depends(get_db)):
    """Lohnvorbereitung: Stunden pro Person als CSV (Excel/DATEV-Import vorbereitbar)."""
    _validate(start, end)
    data = compute_summary(db, user.tenant_id, start, end)
    money = _wages_visible(db, user)
    de = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
    head = ["Name", "E-Mail", "Vertrag (h)", "Geplant (h)", "Gearbeitet (h)", "Freigegeben (h)", "Mehr/Minder (h)",
            "Nacht (h)", "Sonntag (h)", "Feiertag (h)"]
    if money:
        head += ["Grundlohn (EUR)", "Zuschläge (EUR)", "Brutto (EUR)"]
    head += ["Tage über Höchstarbeitszeit", "Wochen über Höchstarbeitszeit", "Minijob-Monate über Grenze"]
    lines = [";".join(head)]
    for r in data["rows"]:
        vals = [csv_safe(r["name"]), csv_safe(r["email"]), de(r["contract_hours"]), de(r["planned_hours"]),
                de(r["worked_hours"]), de(r["approved_hours"]), de(r["overtime_hours"]),
                de(r["night_hours"]), de(r["sunday_hours"]), de(r["holiday_hours"])]
        if money:
            vals += [de(r["labor_cost"]), de(r["surcharge_cost"]), de(r["gross_cost"])]
        vals += [str(r["over_limit_days"]), str(r["over_limit_weeks"]), str(r["minijob_months_over"])]
        lines.append(";".join(vals))
    from ..services.audit import audit
    audit(db, user, "report.export", f"payroll.csv {start:%Y-%m-%d}–{end:%Y-%m-%d} geld={'ja' if money else 'nein'}")
    db.commit()
    body = "\ufeff" + "\r\n".join(lines) + "\r\n"
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="lohnvorbereitung.csv"'})
