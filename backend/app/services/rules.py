"""Planungs-Hinweise (weich): Ruhezeit, Tageshöchstarbeitszeit, Verfügbarkeit.

Harte Fehler (Überschneidung, Urlaub) stehen in common.check_assignable. Die Hinweise hier
darf ein Planer bewusst übergehen (ignore_warnings=true); das wird im Protokoll festgehalten.
"""
from datetime import datetime, time, timedelta
from typing import Optional

from sqlalchemy import select

from ..models import Availability, Shift
from ..utils import to_local

MIN_REST_H = 11


def _net(s: Shift) -> float:
    return max(0.0, (s.end - s.start).total_seconds() / 3600 - s.break_minutes / 60)


def shift_warnings(db, tenant_id: int, user_id: int, start: datetime, end: datetime,
                   exclude_id: Optional[int] = None, break_minutes: int = 0,
                   show_notes: bool = False) -> list[str]:
    from ..models import User
    from .limits import get_limit
    person = db.get(User, user_id)
    minor = bool(person and person.is_minor)
    max_day, max_week = get_limit(db, tenant_id, "max_daily_hours"), get_limit(db, tenant_id, "max_weekly_hours")
    min_rest = MIN_REST_H
    if minor:  # Jugendarbeitsschutzgesetz: 8 h/Tag, 40 h/Woche, 12 h Ruhe, 5-Tage-Woche, 6–20 Uhr
        max_day, max_week, min_rest = 8.0, 40.0, 12
    out: list[str] = []
    q = select(Shift).where(Shift.tenant_id == tenant_id, Shift.user_id == user_id,
                            Shift.deleted_at.is_(None),
                            Shift.end > start - timedelta(hours=min_rest),
                            Shift.start < end + timedelta(hours=min_rest))
    if exclude_id:
        q = q.where(Shift.id != exclude_id)
    for o in db.scalars(q).all():
        if o.end <= start:
            rest = (start - o.end).total_seconds() / 3600
        elif o.start >= end:
            rest = (o.start - end).total_seconds() / 3600
        else:
            continue
        if rest < min_rest:
            out.append(f"Ruhezeit unter {min_rest} Stunden ({rest:.1f} h zur Schicht am {to_local(o.start):%d.%m. %H:%M})")
    # Arbeitszeit pro Tag und pro Woche (lokale Zeit, Pausen abgezogen; Wochen Mo–So)
    mine = (end - start).total_seconds() / 3600 - break_minutes / 60
    ls = to_local(start)
    day, week_start = ls.date(), ls.date() - timedelta(days=ls.weekday())
    window = db.scalars(select(Shift).where(
        Shift.tenant_id == tenant_id, Shift.user_id == user_id, Shift.deleted_at.is_(None),
        Shift.start >= start - timedelta(days=8), Shift.start <= end + timedelta(days=8))).all()
    day_total, week_total = max(0.0, mine), max(0.0, mine)
    for o in window:
        if exclude_id and o.id == exclude_id:
            continue
        od = to_local(o.start).date()
        if od == day:
            day_total += _net(o)
        if week_start <= od < week_start + timedelta(days=7):
            week_total += _net(o)
    if day_total > max_day + 1e-9:
        out.append(f"Mehr als {max_day:g} Stunden Arbeitszeit am {day:%d.%m.%Y} ({day_total:.1f} h)")
    if week_total > max_week + 1e-9:
        out.append(f"Mehr als {max_week:g} Wochenstunden (Woche ab {week_start:%d.%m.}: {week_total:.1f} h)")
    else:
        contract = db.scalar(select(User.weekly_hours).where(User.id == user_id))
        if contract and week_total > contract + 1e-9:
            out.append(f"Über den Vertragsstunden ({contract:g} h/Woche): Woche ab {week_start:%d.%m.} = {week_total:.1f} h")
    if minor:
        ls0, le0 = to_local(start), to_local(end)
        if ls0.hour < 6 or le0.date() > ls0.date() or le0.time() > time(20, 0):
            out.append("Jugendliche dürfen nur zwischen 6 und 20 Uhr arbeiten (§ 14 JArbSchG; Ausnahmen je nach Branche prüfen)")
        if ls0.weekday() >= 5:
            out.append("Jugendliche an Samstag/Sonntag nur in Ausnahmebranchen (§§ 16, 17 JArbSchG) – bitte prüfen")
        days_worked = {to_local(o.start).date() for o in window if not (exclude_id and o.id == exclude_id)
                       and week_start <= to_local(o.start).date() < week_start + timedelta(days=7)} | {ls0.date()}
        if len(days_worked) > 5:
            out.append("Jugendliche: höchstens 5 Arbeitstage pro Woche (§ 15 JArbSchG)")
    if person and person.is_minijob:
        from .limits import get_limit as _g
        limit = person.minijob_limit or _g(db, tenant_id, "minijob_limit")
        m_year, m_month = ls.year, ls.month
        from .payroll import RateTable
        rt = RateTable(db, tenant_id, {user_id: person.hourly_rate})
        month_shifts = db.scalars(select(Shift).where(
            Shift.tenant_id == tenant_id, Shift.user_id == user_id, Shift.deleted_at.is_(None),
            Shift.start >= start - timedelta(days=32), Shift.start <= end + timedelta(days=32))).all()
        money = max(0.0, mine) * rt.rate(user_id, ls.date())
        for o in month_shifts:
            if exclude_id and o.id == exclude_id:
                continue
            lo = to_local(o.start)
            if (lo.year, lo.month) == (m_year, m_month):
                money += _net(o) * rt.rate(user_id, lo.date())
        if money > limit + 1e-9:
            out.append(f"Minijob-Grenze: geplanter Verdienst im Monat {m_month:02d}/{m_year} = {money:.2f} € (Grenze {limit:.2f} €, ohne Zuschläge)")
    # Verfügbarkeit (wöchentlich oder einzelner Tag)
    rows = db.scalars(select(Availability).where(
        Availability.tenant_id == tenant_id, Availability.user_id == user_id)).all()
    out.extend(availability_conflicts(rows, to_local(start), to_local(end), show_notes))
    return out


def availability_conflicts(rows, ls: datetime, le: datetime, show_notes: bool = False) -> list[str]:
    """Konflikte einer Schicht (lokale Zeit ls–le) mit Nichtverfügbarkeiten (wöchentlich oder einzelner Tag)."""
    out: list[str] = []
    names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    for a in rows:
        if a.on_date is not None:
            if not (ls.date() <= a.on_date <= le.date()):
                continue
            label = f"am {a.on_date.strftime('%d.%m.%Y')}"
            if ls.date() == le.date():
                if ls.strftime("%H:%M") < a.end_time and le.strftime("%H:%M") > a.start_time:
                    out.append(f"Person ist laut Verfügbarkeit {label} {a.start_time}–{a.end_time} nicht verfügbar"
                               + (f" ({a.note})" if a.note and show_notes else ""))
            else:
                out.append(f"Schicht über Mitternacht berührt eine Nichtverfügbarkeit {label}")
        elif ls.weekday() == a.weekday and ls.date() == le.date():
            if ls.strftime("%H:%M") < a.end_time and le.strftime("%H:%M") > a.start_time:
                out.append(f"Person ist laut Verfügbarkeit am {names[a.weekday]} {a.start_time}–{a.end_time} nicht verfügbar"
                           + (f" ({a.note})" if a.note and show_notes else ""))
        elif ls.weekday() == a.weekday or le.weekday() == a.weekday:
            out.append(f"Schicht über Mitternacht berührt eine Nichtverfügbarkeit am {names[a.weekday]}")
    return out
