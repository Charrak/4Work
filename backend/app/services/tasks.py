"""Aufgaben: Wiederholungen erzeugen und Statistik berechnen."""
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..models import Department, Task, TaskTemplate, User
from ..utils import local_tz, to_local, utcnow

MAX_CATCHUP_DAYS = 30


def local_to_utc(d: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(d, time(h, m), tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)


def items_json(texts: list[str]) -> str:
    return json.dumps([{"text": t, "done": False, "by": None, "at": None} for t in texts], ensure_ascii=False)


def generate_recurring(db, tenant_id: int, now: Optional[datetime] = None) -> int:
    """Legt für alle aktiven Vorlagen die fälligen Aufgaben an (bis heute, höchstens 30 Tage rückwirkend).
    Wurde die App tagelang nicht geöffnet, entstehen die versäumten Aufgaben trotzdem – als überfällig und offen.
    Idempotent (eindeutig je Vorlage und Tag)."""
    now = now or utcnow()
    today = to_local(now).date()
    created = 0
    for tpl in db.scalars(select(TaskTemplate).where(TaskTemplate.tenant_id == tenant_id,
                                                     TaskTemplate.active.is_(True))).all():
        first = max(tpl.start_date or today, today - timedelta(days=MAX_CATCHUP_DAYS))
        if tpl.last_generated:
            first = max(first, tpl.last_generated + timedelta(days=1))
        if first > today:
            continue
        wd = {int(c) for c in tpl.weekdays}
        texts = json.loads(tpl.items or "[]")
        d = first
        while d <= today:
            if d.weekday() in wd:
                db.add(Task(tenant_id=tenant_id, title=tpl.title, description=tpl.description,
                            department_id=tpl.department_id, assignee_id=tpl.assignee_id,
                            due_at=local_to_utc(d, tpl.due_time), due_date=d, priority=tpl.priority,
                            items=items_json(texts), require_comment=tpl.require_comment,
                            template_id=tpl.id))
                created += 1
            d += timedelta(days=1)
        tpl.last_generated = today
    if db.new or db.dirty:
        try:
            db.commit()
        except IntegrityError:          # zweite gleichzeitige Anfrage war schneller
            db.rollback()
            return 0
    return created


def compute_stats(db, tenant_id: int, start: date, end: date, group_by: str,
                  department_id: Optional[int] = None) -> dict:
    """Statistik für Aufgaben, deren Bezugszeit (Fälligkeit, sonst Anlage) im Zeitraum [start, end] liegt (Ortsdatum)."""
    now = utcnow()
    lo = local_to_utc(start, "00:00")
    hi = local_to_utc(end + timedelta(days=1), "00:00")
    ref = func.coalesce(Task.due_at, Task.created_at)
    q = select(Task).where(Task.tenant_id == tenant_id, Task.deleted_at.is_(None), ref >= lo, ref < hi)
    if department_id:
        q = q.where(Task.department_id == department_id)
    tasks = db.scalars(q).all()
    uids = {t.assignee_id for t in tasks} | {t.completed_by for t in tasks}
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_([i for i in uids if i]))).all()} if uids else {}
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.tenant_id == tenant_id)).all()}

    def blank():
        return {"total": 0, "done": 0, "on_time": 0, "late": 0, "overdue": 0, "open": 0, "delay_min_sum": 0}

    def add(acc, t):
        acc["total"] += 1
        if t.status == "done":
            acc["done"] += 1
            if t.due_at is None or t.completed_at <= t.due_at:
                acc["on_time"] += 1
            else:
                acc["late"] += 1
                acc["delay_min_sum"] += int((t.completed_at - t.due_at).total_seconds() // 60)
        elif t.due_at is not None and t.due_at < now:
            acc["overdue"] += 1
        else:
            acc["open"] += 1

    def key(t) -> str:
        if group_by == "department":
            return depts.get(t.department_id, "Ohne Abteilung") if t.department_id else "Ohne Abteilung"
        if group_by == "task":
            return t.title
        who = t.completed_by if t.status == "done" else t.assignee_id     # erledigt: wer es getan hat
        return names.get(who, "Nicht zugewiesen") if who else "Nicht zugewiesen"

    groups: dict[str, dict] = defaultdict(blank)
    totals, days = blank(), defaultdict(lambda: {"total": 0, "done": 0})
    for t in tasks:
        add(groups[key(t)], t)
        add(totals, t)
        d = to_local(t.due_at or t.created_at).date().isoformat()
        days[d]["total"] += 1
        days[d]["done"] += 1 if t.status == "done" else 0

    def finish(k, a):
        return {"key": k, **a,
                "done_rate": round(a["done"] / a["total"], 3) if a["total"] else None,
                "on_time_rate": round(a["on_time"] / a["done"], 3) if a["done"] else None,
                "avg_delay_min": round(a["delay_min_sum"] / a["late"]) if a["late"] else 0}

    rows = sorted((finish(k, a) for k, a in groups.items()), key=lambda r: (-r["total"], r["key"]))
    return {"start": start.isoformat(), "end": end.isoformat(), "group_by": group_by,
            "totals": finish("Gesamt", totals), "groups": rows,
            "days": [{"date": d, **v} for d, v in sorted(days.items())]}
