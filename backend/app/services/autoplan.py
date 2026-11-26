"""Autoplaner: verteilt Schichten fair auf passende Personen und rechnet Stunden je Abrechnungszeitraum.

Abrechnungszeitraum: Einstellung `period_start_day` (Standard 15 = vom 15. bis 14. des Folgemonats).
Pro Person und Zeitraum:
  Soll   = Wochenstunden × Tage/7 (nur Tage im Vertrag, Eintritt/Austritt berücksichtigt)
  Urlaub = genehmigte Abwesenheit an Arbeitstagen zählt als erfüllt (Tagesstunden = Wochenstunden / Arbeitstage)
  Ziel   = Soll − Urlaubsgutschrift   ("von": so viele Stunden sollen geplant werden)
  Max    = Ziel × (1 + Überstunden-%) bzw. bei Minijob höchstens Grenze / Stundensatz   ("bis")
Die Vergabe ist ein deterministisches Greedy-Verfahren: Schichten in zeitlicher Reihenfolge, je Schicht erhält die
Person mit der niedrigsten Auslastung (geplant / Ziel), die alle Regeln einhält (Vertrag, Arbeitstage, Urlaub,
Verfügbarkeit, Überschneidung, Stundenmax., Ruhezeit, Tages-/Wochenmaximum, Jugendschutz, Minijob).
Bereits vorhandene Schichten (gleiche Abteilung, gleiche Zeit) zählen als Bedarf und werden nicht doppelt angelegt;
unbesetzte davon werden befüllt. Die Vorschau läuft in derselben Transaktion und wird zurückgerollt.
"""
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select

from ..models import Availability, LeaveRequest, Shift, ShiftTemplate, User
from ..utils import parse_work_days, to_local
from .limits import get_limit
from .payroll import RateTable
from .rules import availability_conflicts, shift_warnings
from .tasks import local_to_utc

MAX_SHIFTS = 1500


def _add_month(d: date, n: int = 1) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def period_bounds(d: date, start_day: int) -> tuple[date, date]:
    """Abrechnungszeitraum (erster, letzter Tag) zu einem Datum."""
    start_day = max(1, min(28, int(start_day)))
    if start_day == 1:
        first = d.replace(day=1)
        return first, _add_month(first) - timedelta(days=1)
    first_of_month = d.replace(day=1)
    ps = first_of_month.replace(day=start_day) if d.day >= start_day else _add_month(first_of_month, -1).replace(day=start_day)
    return ps, _add_month(ps.replace(day=1)).replace(day=start_day) - timedelta(days=1)


def periods_between(a: date, b: date, start_day: int) -> list[tuple[date, date]]:
    out, cur = [], a
    while cur <= b:
        ps, pe = period_bounds(cur, start_day)
        out.append((ps, pe))
        cur = pe + timedelta(days=1)
    return out


def hours(start: datetime, end: datetime, brk: int = 0) -> float:
    return max(0.0, (end - start).total_seconds() / 3600 - brk / 60)


def classify(warning: str) -> str:
    w = warning
    if w.startswith("Ruhezeit"):
        return "Ruhezeit"
    if "Verfügbarkeit" in w or "Nichtverfügbarkeit" in w:
        return "nicht verfügbar"
    if w.startswith("Über den Vertragsstunden"):
        return "Wochenstunden laut Vertrag"
    if w.startswith("Mehr als"):
        return "Arbeitszeit-Höchstgrenze"
    if w.startswith("Minijob"):
        return "Minijob-Grenze"
    if w.startswith("Jugendliche"):
        return "Jugendschutz"
    return "Planungsregel"


class Person:
    def __init__(self, user: User, avail: list[Availability]):
        self.u = user
        self.avail = avail
        self.leave_days: set[date] = set()      # genehmigte Abwesenheit (blockiert)
        self.credit_days: set[date] = set()     # davon: zählen als erfüllt (nicht "Wunsch")
        self.busy: list[tuple[datetime, datetime]] = []
        self.work_days = parse_work_days(user.work_days)
        self.planned: dict[date, float] = {}    # Periodenstart -> Stunden (vorhanden + neu)
        self.before: dict[date, float] = {}
        self.new: dict[date, float] = {}
        self.pool: dict[date, float] = {}

    def active_on(self, d: date) -> bool:
        u = self.u
        return not ((u.hire_date and d < u.hire_date) or (u.contract_end and d > u.contract_end))


def _budget(p: Person, ps: date, pe: date, pct: float, rt: RateTable, mj_default: float) -> dict:
    u = p.u
    lo, hi = max(ps, u.hire_date or ps), min(pe, u.contract_end or pe)
    days = max(0, (hi - lo).days + 1)
    soll = round(u.weekly_hours * days / 7, 2) if u.weekly_hours else None
    credit = 0.0
    if soll is not None and p.work_days:
        daily = u.weekly_hours / len(p.work_days)
        n = sum(1 for d in p.credit_days if lo <= d <= hi and d.weekday() in p.work_days)
        credit = round(n * daily, 2)
    ziel = round(max(0.0, soll - credit), 2) if soll is not None else None
    cap = round(ziel * (1 + pct / 100), 2) if ziel is not None else None
    mj_h = None
    if u.is_minijob:
        limit = u.minijob_limit or mj_default
        rate = rt.rate(u.id, pe)
        if rate > 0:
            mj_h = round(limit / rate, 2)
            cap = mj_h if cap is None else min(cap, mj_h)
    target = ziel if ziel is not None else mj_h
    return {"soll": soll, "credit": credit, "ziel": ziel, "cap": cap, "target": target, "minijob_h": mj_h}


def run(db, tenant_id: int, body, dry_run: bool) -> dict:
    """Plant (oder zeigt nur) den Vorschlag. Bei dry_run wird alles zurückgerollt."""
    start_day = int(get_limit(db, tenant_id, "period_start_day"))
    mj_default = get_limit(db, tenant_id, "minijob_limit")
    d0, d1 = body.start, body.end
    periods = periods_between(d0, d1, start_day)
    win_lo = local_to_utc(periods[0][0] - timedelta(days=2), "00:00")
    win_hi = local_to_utc(periods[-1][1] + timedelta(days=3), "00:00")

    users = [u for u in db.scalars(select(User).where(
        User.tenant_id == tenant_id, User.deleted_at.is_(None), User.is_active.is_(True))).all()
        if body.department_id in u.department_ids and (not body.user_ids or u.id in body.user_ids)]
    users.sort(key=lambda u: u.id)
    uids = [u.id for u in users]
    avail: dict[int, list[Availability]] = {i: [] for i in uids}
    for a in db.scalars(select(Availability).where(Availability.tenant_id == tenant_id, Availability.user_id.in_(uids))).all():
        avail[a.user_id].append(a)
    people = {u.id: Person(u, avail[u.id]) for u in users}
    for lv in db.scalars(select(LeaveRequest).where(
            LeaveRequest.tenant_id == tenant_id, LeaveRequest.user_id.in_(uids), LeaveRequest.status == "approved",
            LeaveRequest.start_date <= periods[-1][1], LeaveRequest.end_date >= periods[0][0])).all():
        d = lv.start_date
        while d <= lv.end_date:
            people[lv.user_id].leave_days.add(d)
            if lv.kind != "wish":
                people[lv.user_id].credit_days.add(d)
            d += timedelta(days=1)

    # vorhandene Schichten (alle Abteilungen: Überschneidung/Stunden; Abteilung: Bedarf)
    existing = list(db.scalars(select(Shift).where(
        Shift.tenant_id == tenant_id, Shift.deleted_at.is_(None), Shift.start >= win_lo, Shift.start < win_hi)).all())
    key_of = lambda dt: period_bounds(to_local(dt).date(), start_day)[0]  # noqa: E731
    for s in existing:
        p = people.get(s.user_id) if s.user_id else None
        if p:
            p.busy.append((s.start, s.end))
            k = key_of(s.start)
            p.planned[k] = p.planned.get(k, 0.0) + hours(s.start, s.end, s.break_minutes)
            p.before[k] = p.planned[k]

    rt = RateTable(db, tenant_id, {u.id: u.hourly_rate for u in users})
    budgets = {(p.u.id, ps): _budget(p, ps, pe, body.overtime_pct, rt, mj_default)
               for p in people.values() for ps, pe in periods}

    # Bedarf ausdehnen
    wanted: dict[tuple, dict] = {}
    tpl_cache: dict[int, ShiftTemplate] = {}
    for slot in body.slots:
        st, en, brk, note = slot.start_time, slot.end_time, slot.break_minutes, slot.note
        if slot.template_id:
            t = tpl_cache.get(slot.template_id) or db.get(ShiftTemplate, slot.template_id)
            if not t or t.tenant_id != tenant_id:
                from fastapi import HTTPException
                raise HTTPException(404, "Schichtvorlage nicht gefunden")
            tpl_cache[slot.template_id] = t
            st, en, brk, note = t.start_time, t.end_time, t.break_minutes, note or t.note
        d = d0
        while d <= d1:
            if d.weekday() in slot.weekdays:
                s = local_to_utc(d, st)
                e = local_to_utc(d if en > st else d + timedelta(days=1), en)
                k = (s, e, brk)
                if k in wanted:
                    wanted[k]["count"] += slot.count
                else:
                    wanted[k] = {"date": d, "start": s, "end": e, "brk": brk, "count": slot.count, "note": note}
            d += timedelta(days=1)
    items = sorted(wanted.values(), key=lambda x: (x["start"], x["end"]))
    if len(items) > MAX_SHIFTS:
        from fastapi import HTTPException
        raise HTTPException(422, f"Zu viele Schichten auf einmal ({len(items)}); bitte den Zeitraum verkleinern")

    def blocked(p: Person, it: dict) -> Optional[str]:
        d = it["date"]
        if not p.active_on(d):
            return "nicht im Vertragszeitraum"
        if body.respect_work_days and d.weekday() not in p.work_days:
            return "kein Arbeitstag laut Vertrag"
        if any(x in p.leave_days for x in (d, to_local(it["end"]).date())):
            return "Urlaub/Abwesenheit"
        if availability_conflicts(p.avail, to_local(it["start"]), to_local(it["end"])):
            return "nicht verfügbar"
        return None

    # Pool: Stunden, die eine Person grundsätzlich übernehmen könnte (ohne Budget/Überschneidung)
    for it in items:
        k = period_bounds(it["date"], start_day)[0]
        h = hours(it["start"], it["end"], it["brk"])
        for p in people.values():
            if blocked(p, it) is None:
                p.pool[k] = p.pool.get(k, 0.0) + h * it["count"]

    created: list[dict] = []
    unfilled: list[dict] = []
    counts = Counter()
    dept = body.department_id
    for it in items:
        s, e, brk = it["start"], it["end"], it["brk"]
        h = hours(s, e, brk)
        k = period_bounds(it["date"], start_day)[0]
        cover = [x for x in existing if x.department_id == dept and x.start == s and x.end == e]
        open_shifts = [x for x in cover if x.user_id is None]
        to_fill = len(open_shifts) + max(0, it["count"] - len(cover))
        reasons: Counter = Counter()
        missing = 0
        for n in range(to_fill):
            open_sh = open_shifts[n] if n < len(open_shifts) else None
            cands = []
            for p in people.values():
                r = blocked(p, it)
                if not r and any(a < e and s < b for a, b in p.busy):
                    r = "Überschneidung"
                if not r:
                    cap = budgets[(p.u.id, k)]["cap"]
                    if cap is not None and p.planned.get(k, 0.0) + h > cap + 1e-9:
                        r = "Stundenbudget erreicht"
                if r:
                    reasons[r] += 1
                    continue
                tgt = budgets[(p.u.id, k)]["target"]
                load = (p.planned.get(k, 0.0) + h) / tgt if tgt else 1.0 + p.planned.get(k, 0.0) / 1000
                cands.append((load, p.u.id, p))
            cands.sort(key=lambda c: (c[0], c[1]))
            chosen = None
            for _, _, p in cands:
                w = shift_warnings(db, tenant_id, p.u.id, s, e, open_sh.id if open_sh else None, brk, False)
                if w:
                    reasons[classify(w[0])] += 1
                    continue
                chosen = p
                break
            if chosen is None:
                missing += 1
                if open_sh is None and body.create_open:
                    sh = Shift(tenant_id=tenant_id, department_id=dept, user_id=None, start=s, end=e,
                               note=it["note"], break_minutes=brk)
                    db.add(sh)
                    db.flush()
                    existing.append(sh)
                    counts["open_created"] += 1
                    created.append(_row(sh, it, None, True))
                continue
            if open_sh is not None:
                open_sh.user_id = chosen.u.id
                db.flush()
                sh = open_sh
                counts["filled_existing"] += 1
            else:
                sh = Shift(tenant_id=tenant_id, department_id=dept, user_id=chosen.u.id, start=s, end=e,
                           note=it["note"], break_minutes=brk)
                db.add(sh)
                db.flush()
                existing.append(sh)
                counts["created"] += 1
            chosen.busy.append((s, e))
            chosen.planned[k] = chosen.planned.get(k, 0.0) + h
            chosen.new[k] = chosen.new.get(k, 0.0) + h
            created.append(_row(sh, it, chosen.u.name, False))
        if missing:
            unfilled.append({"date": it["date"].isoformat(), "start": _z(s), "end": _z(e), "missing": missing,
                             "reasons": dict(reasons.most_common())})
    counts["unfilled"] = sum(u["missing"] for u in unfilled)

    rows = []
    for p in people.values():
        for ps, pe in periods:
            b = budgets[(p.u.id, ps)]
            before, new = p.before.get(ps, 0.0), p.new.get(ps, 0.0)
            total = p.planned.get(ps, 0.0)
            rest = round(b["cap"] - total, 2) if b["cap"] is not None else None
            pool = round(p.pool.get(ps, 0.0), 2)
            rows.append({
                "user_id": p.u.id, "name": p.u.name, "period_start": ps.isoformat(), "period_end": pe.isoformat(),
                "weekly_hours": p.u.weekly_hours, "is_minijob": p.u.is_minijob,
                "soll_h": b["soll"], "urlaub_h": b["credit"], "ziel_h": b["ziel"], "max_h": b["cap"],
                "minijob_max_h": b["minijob_h"],
                "geplant_vorher_h": round(before, 2), "neu_h": round(new, 2), "gesamt_h": round(total, 2),
                "rest_h": rest, "verfuegbar_h": pool,
                "moeglich_h": min(rest, pool) if rest is not None else pool,
            })
    result = {"applied": not dry_run, "start_day": start_day, "counts": dict(counts), "created": created,
              "unfilled": unfilled, "people": rows,
              "periods": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in periods]}
    if dry_run:
        db.rollback()
        for r in result["created"]:
            r["shift_id"] = None  # in der Vorschau nicht gespeichert
    return result


def hours_overview(db, tenant_id: int, department_id: Optional[int], day: date, overtime_pct: float = 0.0) -> dict:
    """Stundenübersicht (Soll/Ziel/Max/geplant/Rest) für den Abrechnungszeitraum, in dem `day` liegt."""
    start_day = int(get_limit(db, tenant_id, "period_start_day"))
    ps, pe = period_bounds(day, start_day)
    mj_default = get_limit(db, tenant_id, "minijob_limit")
    users = [u for u in db.scalars(select(User).where(
        User.tenant_id == tenant_id, User.deleted_at.is_(None), User.is_active.is_(True)).order_by(User.name)).all()
        if department_id is None or department_id in u.department_ids]
    uids = [u.id for u in users]
    people = {u.id: Person(u, []) for u in users}
    for lv in db.scalars(select(LeaveRequest).where(
            LeaveRequest.tenant_id == tenant_id, LeaveRequest.user_id.in_(uids), LeaveRequest.status == "approved",
            LeaveRequest.start_date <= pe, LeaveRequest.end_date >= ps)).all():
        d = lv.start_date
        while d <= lv.end_date:
            if lv.kind != "wish":
                people[lv.user_id].credit_days.add(d)
            d += timedelta(days=1)
    lo, hi = local_to_utc(ps, "00:00"), local_to_utc(pe + timedelta(days=1), "00:00")
    planned: dict[int, float] = {}
    for s in db.scalars(select(Shift).where(Shift.tenant_id == tenant_id, Shift.deleted_at.is_(None),
                                            Shift.user_id.in_(uids), Shift.start >= lo, Shift.start < hi)).all():
        planned[s.user_id] = planned.get(s.user_id, 0.0) + hours(s.start, s.end, s.break_minutes)
    rt = RateTable(db, tenant_id, {u.id: u.hourly_rate for u in users})
    rows = []
    for p in people.values():
        b = _budget(p, ps, pe, overtime_pct, rt, mj_default)
        tot = round(planned.get(p.u.id, 0.0), 2)
        rows.append({"user_id": p.u.id, "name": p.u.name, "weekly_hours": p.u.weekly_hours,
                     "is_minijob": p.u.is_minijob, "soll_h": b["soll"], "urlaub_h": b["credit"],
                     "ziel_h": b["ziel"], "max_h": b["cap"], "minijob_max_h": b["minijob_h"],
                     "gesamt_h": tot, "rest_h": round(b["cap"] - tot, 2) if b["cap"] is not None else None})
    return {"period_start": ps.isoformat(), "period_end": pe.isoformat(), "start_day": start_day, "people": rows}


def _z(dt: datetime) -> str:
    return dt.isoformat() + "Z"


def _row(sh: Shift, it: dict, name: Optional[str], is_open: bool) -> dict:
    return {"shift_id": sh.id, "date": it["date"].isoformat(), "start": _z(sh.start), "end": _z(sh.end),
            "break_minutes": sh.break_minutes, "user_id": sh.user_id, "user_name": name, "open": is_open,
            "hours": round(hours(sh.start, sh.end, sh.break_minutes), 2)}
