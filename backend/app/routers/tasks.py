"""Aufgaben und Checklisten mit Abhaken und Statistik.

Rechte (einzeln vergebbar):
  tasks.do           eigene Aufgaben sehen und abhaken (zugewiesen an mich, oder an meine Abteilung/alle)
  tasks.create       Aufgaben anlegen und zuweisen; eigene Aufgaben bearbeiten/löschen
  tasks.manage       alle Aufgaben sehen, bearbeiten, löschen, für andere abhaken; Checklisten-Vorlagen
  tasks.stats        Statistik nach Abteilung und Aufgabe
  tasks.stats_people Statistik pro Person (Leistungs-/Verhaltenskontrolle: bewusst eigenes Recht, Standard nur Administrator)
"""
import json
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require
from ..models import Department, Task, TaskTemplate, User
from ..schemas import (CompleteIn, ItemToggleIn, TaskIn, TaskItemOut, TaskOut, TaskTemplateIn,
                       TaskTemplateOut, TaskUpdate)
from ..services.audit import audit
from ..services.common import (changed, check_version, get_department_or_404, get_user_or_404,
                               notify_users, permissions_for)
from ..services.tasks import compute_stats, generate_recurring, items_json
from ..utils import csv_safe, to_local, utcnow

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
template_router = APIRouter(prefix="/api/task-templates", tags=["tasks"])

ANY = {"tasks.do", "tasks.create", "tasks.manage"}


def _perms(db: Session, user: User) -> set[str]:
    p = permissions_for(db, user)
    if not (p & ANY):
        raise HTTPException(403, "Keine Berechtigung")
    return p


def _is_mine(t: Task, user: User) -> bool:
    """Zugewiesen an mich – oder an niemanden Bestimmten, aber an meine Abteilung bzw. alle."""
    if t.assignee_id is not None:
        return t.assignee_id == user.id
    return t.department_id is None or t.department_id in user.department_ids


def _mine_cond(user: User):
    return or_(Task.assignee_id == user.id,
               and_(Task.assignee_id.is_(None),
                    or_(Task.department_id.is_(None), Task.department_id.in_(user.department_ids or [0]))))


def _can_see(t: Task, user: User, perms: set[str]) -> bool:
    return ("tasks.manage" in perms or (t.created_by == user.id and "tasks.create" in perms)
            or ("tasks.do" in perms and _is_mine(t, user)))


def _can_complete(t: Task, user: User, perms: set[str]) -> bool:
    return "tasks.manage" in perms or ("tasks.do" in perms and _is_mine(t, user))


def _can_edit(t: Task, user: User, perms: set[str]) -> bool:
    return t.status == "open" and ("tasks.manage" in perms or ("tasks.create" in perms and t.created_by == user.id))


def _items(t: Task) -> list[dict]:
    try:
        return json.loads(t.items or "[]")
    except ValueError:
        return []


def _outs(db: Session, tasks: list[Task], user: User, perms: set[str]) -> list[TaskOut]:
    items_by = {t.id: _items(t) for t in tasks}
    ids = {t.assignee_id for t in tasks} | {t.completed_by for t in tasks} | {t.created_by for t in tasks}
    ids |= {i.get("by") for lst in items_by.values() for i in lst}
    ids.discard(None)
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids))).all()} if ids else {}
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.tenant_id == user.tenant_id)).all()}
    now = utcnow()
    out = []
    for t in tasks:
        out.append(TaskOut(
            id=t.id, title=t.title, description=t.description, department_id=t.department_id,
            department_name=depts.get(t.department_id), assignee_id=t.assignee_id,
            assignee_name=names.get(t.assignee_id), due_at=t.due_at, priority=t.priority,
            items=[TaskItemOut(text=i["text"], done=bool(i.get("done")), by_name=names.get(i.get("by")),
                               at=_parse(i.get("at"))) for i in items_by[t.id]],
            require_comment=t.require_comment, status=t.status, completed_at=t.completed_at,
            completed_by=t.completed_by, completed_by_name=names.get(t.completed_by),
            completion_comment=t.completion_comment, template_id=t.template_id, created_by=t.created_by,
            created_by_name=names.get(t.created_by),
            overdue=t.status == "open" and t.due_at is not None and t.due_at < now,
            can_complete=_can_complete(t, user, perms), can_edit=_can_edit(t, user, perms), version=t.version))
    return out


def _parse(v):
    from datetime import datetime
    return datetime.fromisoformat(v) if v else None


def _get(db: Session, user: User, perms: set[str], task_id: int) -> Task:
    t = db.get(Task, task_id)
    if not t or t.tenant_id != user.tenant_id or t.deleted_at or not _can_see(t, user, perms):
        raise HTTPException(404, "Aufgabe nicht gefunden")      # 404 statt 403: Existenz nicht verraten
    return t


def _check_targets(db: Session, user: User, body: TaskIn) -> None:
    if body.department_id:
        get_department_or_404(db, user.tenant_id, body.department_id)
    if body.assignee_id:
        get_user_or_404(db, user.tenant_id, body.assignee_id)


@router.get("", response_model=list[TaskOut])
def list_tasks(status: Literal["open", "done", "all"] = "open", scope: Literal["mine", "all"] = "mine",
               department_id: Optional[int] = None, assignee_id: Optional[int] = None, days: int = 14,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = _perms(db, user)
    if scope == "all" and "tasks.manage" not in perms:
        raise HTTPException(403, "Keine Berechtigung")
    generate_recurring(db, user.tenant_id)
    q = select(Task).where(Task.tenant_id == user.tenant_id, Task.deleted_at.is_(None))
    if scope == "mine":
        q = q.where(_mine_cond(user))
    if department_id:
        q = q.where(Task.department_id == department_id)
    if assignee_id:
        q = q.where(Task.assignee_id == assignee_id)
    if status == "open":
        q = q.where(Task.status == "open").order_by(Task.due_at.is_(None), Task.due_at, Task.priority.desc())
    elif status == "done":
        q = q.where(Task.status == "done", Task.completed_at >= utcnow() - timedelta(days=min(max(days, 1), 365))) \
             .order_by(Task.completed_at.desc())
    else:
        q = q.order_by(Task.id.desc())
    return _outs(db, db.scalars(q.limit(500)).all(), user, perms)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = _perms(db, user)
    if not perms & {"tasks.create", "tasks.manage"}:
        raise HTTPException(403, "Keine Berechtigung")
    _check_targets(db, user, body)
    t = Task(tenant_id=user.tenant_id, created_by=user.id, items=items_json(body.items),
             **body.model_dump(exclude={"items"}))
    db.add(t)
    db.flush()
    audit(db, user, "task.create", f"task={t.id} zugewiesen={t.assignee_id}", request)
    if t.assignee_id and t.assignee_id != user.id:
        notify_users(db, user.tenant_id, [t.assignee_id], "Neue Aufgabe", t.title)
    db.commit()
    changed(user.tenant_id, "tasks")
    return _outs(db, [t], user, perms)[0]


@router.get("/stats")
def stats(start: date, end: date, group_by: Literal["department", "task", "person"] = "department",
          department_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _stats(start, end, group_by, department_id, user, db)


@router.get("/stats.csv")
def stats_csv(start: date, end: date, group_by: Literal["department", "task", "person"] = "department",
              department_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = _stats(start, end, group_by, department_id, user, db)
    label = {"department": "Abteilung", "task": "Aufgabe", "person": "Person"}[group_by]
    pct = lambda x: "" if x is None else f"{x * 100:.1f}".replace(".", ",")
    lines = [f"{label};Aufgaben;Erledigt;Pünktlich;Verspätet;Überfällig offen;Noch nicht fällig;Erledigt (%);Pünktlich (%);Ø Verspätung (Min.)"]
    for r in data["groups"] + [data["totals"]]:
        lines.append(";".join([csv_safe(r["key"]), str(r["total"]), str(r["done"]), str(r["on_time"]), str(r["late"]),
                               str(r["overdue"]), str(r["open"]), pct(r["done_rate"]), pct(r["on_time_rate"]),
                               str(r["avg_delay_min"])]))
    return Response("﻿" + "\r\n".join(lines) + "\r\n", media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="aufgaben-statistik.csv"'})


def _stats(start: date, end: date, group_by: str, department_id: Optional[int], user: User, db: Session) -> dict:
    perms = permissions_for(db, user)
    if "tasks.stats" not in perms and not (group_by == "person" and "tasks.stats_people" in perms):
        raise HTTPException(403, "Keine Berechtigung")
    if group_by == "person" and "tasks.stats_people" not in perms:
        raise HTTPException(403, "Auswertung pro Person nur mit gesondertem Recht")
    if end < start or (end - start).days > 366:
        raise HTTPException(422, "Zeitraum ungültig (maximal 366 Tage)")
    generate_recurring(db, user.tenant_id)
    if group_by == "person":
        audit(db, user, "task.stats_people", f"{start}..{end}")
        db.commit()
    return compute_stats(db, user.tenant_id, start, end, group_by, department_id)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = _perms(db, user)
    return _outs(db, [_get(db, user, perms, task_id)], user, perms)[0]


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    perms = _perms(db, user)
    t = _get(db, user, perms, task_id)
    if not _can_edit(t, user, perms):
        raise HTTPException(403, "Diese Aufgabe darf nicht bearbeitet werden")
    check_version(t, body.version)
    _check_targets(db, user, body)
    old_assignee = t.assignee_id
    old = {i["text"]: i for i in _items(t)}
    new_items = [old.get(x, {"text": x, "done": False, "by": None, "at": None}) for x in body.items]
    for k, v in body.model_dump(exclude={"items", "version"}).items():
        setattr(t, k, v)
    t.items = json.dumps(new_items, ensure_ascii=False)
    t.version += 1
    audit(db, user, "task.update", f"task={t.id}", request)
    if t.assignee_id and t.assignee_id != old_assignee and t.assignee_id != user.id:
        notify_users(db, user.tenant_id, [t.assignee_id], "Neue Aufgabe", t.title)
    db.commit()
    changed(user.tenant_id, "tasks")
    return _outs(db, [t], user, perms)[0]


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = _perms(db, user)
    t = _get(db, user, perms, task_id)
    if "tasks.manage" not in perms and not (t.created_by == user.id and "tasks.create" in perms and t.status == "open"):
        raise HTTPException(403, "Diese Aufgabe darf nicht gelöscht werden")
    t.deleted_at = utcnow()
    audit(db, user, "task.delete", f"task={t.id} titel={t.title[:80]}", request)
    db.commit()
    changed(user.tenant_id, "tasks")


@router.post("/{task_id}/items/{index}", response_model=TaskOut)
def toggle_item(task_id: int, index: int, body: ItemToggleIn, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    perms = _perms(db, user)
    t = _get(db, user, perms, task_id)
    if not _can_complete(t, user, perms):
        raise HTTPException(403, "Keine Berechtigung")
    if t.status != "open":
        raise HTTPException(409, "Die Aufgabe ist bereits erledigt")
    items = _items(t)
    if not 0 <= index < len(items):
        raise HTTPException(404, "Punkt nicht gefunden")
    items[index].update(done=body.done, by=user.id if body.done else None,
                        at=utcnow().isoformat() if body.done else None)
    t.items = json.dumps(items, ensure_ascii=False)
    t.version += 1
    db.commit()
    changed(user.tenant_id, "tasks")
    return _outs(db, [t], user, perms)[0]


@router.post("/{task_id}/complete", response_model=TaskOut)
def complete(task_id: int, body: CompleteIn, request: Request, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    """Idempotent: Bereits Erledigtes bleibt unverändert (wichtig, wenn eine offline gemerkte Aktion später ankommt)."""
    perms = _perms(db, user)
    t = _get(db, user, perms, task_id)
    if not _can_complete(t, user, perms):
        raise HTTPException(403, "Sie dürfen diese Aufgabe nicht abhaken")
    if t.status == "done":
        return _outs(db, [t], user, perms)[0]
    open_items = [i["text"] for i in _items(t) if not i.get("done")]
    if open_items:
        raise HTTPException(422, f"Es sind noch {len(open_items)} Punkt(e) offen")
    comment = body.comment.strip()
    if t.require_comment and not comment:
        raise HTTPException(422, "Für diese Aufgabe ist ein Kommentar erforderlich")
    t.status, t.completed_at, t.completed_by, t.completion_comment = "done", utcnow(), user.id, comment
    t.version += 1
    if t.created_by and t.created_by != user.id:
        notify_users(db, user.tenant_id, [t.created_by], "Aufgabe erledigt", f"{t.title} ({user.name})")
    db.commit()
    changed(user.tenant_id, "tasks")
    return _outs(db, [t], user, perms)[0]


@router.post("/{task_id}/reopen", response_model=TaskOut)
def reopen(task_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = _perms(db, user)
    t = _get(db, user, perms, task_id)
    if t.status != "done":
        return _outs(db, [t], user, perms)[0]
    if "tasks.manage" not in perms and t.completed_by != user.id:
        raise HTTPException(403, "Nur wer die Aufgabe abgehakt hat (oder die Verwaltung) darf sie wieder öffnen")
    t.status, t.completed_at, t.completed_by, t.completion_comment = "open", None, None, ""
    t.version += 1
    audit(db, user, "task.reopen", f"task={t.id}", request)
    db.commit()
    changed(user.tenant_id, "tasks")
    return _outs(db, [t], user, perms)[0]


# ---------- Checklisten-Vorlagen (wiederkehrende Aufgaben) ----------
def _tpl(db: Session, tenant_id: int, tid: int) -> TaskTemplate:
    t = db.get(TaskTemplate, tid)
    if not t or t.tenant_id != tenant_id:
        raise HTTPException(404, "Vorlage nicht gefunden")
    return t


def _tpl_fields(body: TaskTemplateIn) -> dict:
    d = body.model_dump(exclude={"items"})
    d["items"] = json.dumps(body.items, ensure_ascii=False)
    return d


def _tpl_out(t: TaskTemplate) -> TaskTemplateOut:
    return TaskTemplateOut(id=t.id, title=t.title, description=t.description, department_id=t.department_id,
                           assignee_id=t.assignee_id, weekdays=t.weekdays, due_time=t.due_time,
                           items=json.loads(t.items or "[]"), require_comment=t.require_comment,
                           priority=t.priority, active=t.active, last_generated=t.last_generated)


@template_router.get("", response_model=list[TaskTemplateOut])
def list_templates(user: User = Depends(require("tasks.manage")), db: Session = Depends(get_db)):
    return [_tpl_out(t) for t in db.scalars(select(TaskTemplate).where(TaskTemplate.tenant_id == user.tenant_id)
                                            .order_by(TaskTemplate.title)).all()]


@template_router.post("", response_model=TaskTemplateOut, status_code=201)
def create_template(body: TaskTemplateIn, request: Request, user: User = Depends(require("tasks.manage")),
                    db: Session = Depends(get_db)):
    _check_targets(db, user, body)                      # type: ignore[arg-type]
    t = TaskTemplate(tenant_id=user.tenant_id, start_date=to_local(utcnow()).date(), **_tpl_fields(body))
    db.add(t)
    db.flush()
    audit(db, user, "task_template.create", f"template={t.id}", request)
    db.commit()
    changed(user.tenant_id, "tasks")
    return _tpl_out(t)


@template_router.put("/{tid}", response_model=TaskTemplateOut)
def update_template(tid: int, body: TaskTemplateIn, request: Request, user: User = Depends(require("tasks.manage")),
                    db: Session = Depends(get_db)):
    t = _tpl(db, user.tenant_id, tid)
    _check_targets(db, user, body)                      # type: ignore[arg-type]
    for k, v in _tpl_fields(body).items():
        setattr(t, k, v)
    audit(db, user, "task_template.update", f"template={t.id}", request)
    db.commit()
    changed(user.tenant_id, "tasks")
    return _tpl_out(t)


@template_router.delete("/{tid}", status_code=204)
def delete_template(tid: int, request: Request, user: User = Depends(require("tasks.manage")),
                    db: Session = Depends(get_db)):
    t = _tpl(db, user.tenant_id, tid)
    for task in db.scalars(select(Task).where(Task.template_id == t.id)).all():
        task.template_id = None                          # bereits erzeugte Aufgaben bleiben (Statistik) erhalten
    db.flush()
    db.delete(t)
    audit(db, user, "task_template.delete", f"template={tid}", request)
    db.commit()
    changed(user.tenant_id, "tasks")
