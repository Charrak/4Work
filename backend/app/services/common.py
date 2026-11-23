from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select

from ..hub import hub
from ..models import (Department, LeaveRequest, PushSubscription, RolePermission, Shift, User)
from ..permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
from . import push


def permissions_for(db, user: User) -> set[str]:
    if user.role == "admin":
        return set(ALL_PERMISSIONS)
    rows = db.scalars(select(RolePermission.permission).where(
        RolePermission.tenant_id == user.tenant_id, RolePermission.role == user.role)).all()
    return set(rows)


def seed_role_permissions(db, tenant_id: int) -> None:
    for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
        for p in perms:
            db.add(RolePermission(tenant_id=tenant_id, role=role, permission=p))


def check_version(obj, client_version: int) -> None:
    """Optimistische Sperre: Der Client muss die Version kennen, die er bearbeitet hat."""
    if obj.version != client_version:
        raise HTTPException(409, detail={
            "message": "Der Datensatz wurde zwischenzeitlich geändert. Bitte neu laden.",
            "current_version": obj.version})


def get_user_or_404(db, tenant_id: int, user_id: int, include_deleted: bool = False) -> User:
    u = db.get(User, user_id)
    if not u or u.tenant_id != tenant_id or (u.deleted_at and not include_deleted):
        raise HTTPException(404, "Benutzer nicht gefunden")
    return u


def get_department_or_404(db, tenant_id: int, dept_id: int) -> Department:
    d = db.get(Department, dept_id)
    if not d or d.tenant_id != tenant_id:
        raise HTTPException(404, "Abteilung nicht gefunden")
    return d


def has_overlap(db, tenant_id: int, user_id: int, start: datetime, end: datetime,
                exclude_id: Optional[int] = None) -> bool:
    q = select(Shift.id).where(
        Shift.tenant_id == tenant_id, Shift.user_id == user_id, Shift.deleted_at.is_(None),
        Shift.start < end, Shift.end > start)
    if exclude_id:
        q = q.where(Shift.id != exclude_id)
    return db.scalars(q.limit(1)).first() is not None


def has_leave(db, tenant_id: int, user_id: int, start: datetime, end: datetime) -> bool:
    q = select(LeaveRequest.id).where(
        LeaveRequest.tenant_id == tenant_id, LeaveRequest.user_id == user_id,
        LeaveRequest.status == "approved",
        LeaveRequest.start_date <= end.date(), LeaveRequest.end_date >= start.date())
    return db.scalars(q.limit(1)).first() is not None


def check_assignable(db, tenant_id: int, user_id: int, start: datetime, end: datetime,
                     exclude_id: Optional[int] = None) -> None:
    if has_overlap(db, tenant_id, user_id, start, end, exclude_id):
        raise HTTPException(409, "Überschneidung mit einer anderen Schicht dieser Person")
    if has_leave(db, tenant_id, user_id, start, end):
        raise HTTPException(409, "Die Person hat in diesem Zeitraum genehmigten Urlaub")


def notify_users(db, tenant_id: int, user_ids, title: str, body: str, event: str = "notification") -> None:
    ids = sorted({i for i in user_ids if i})
    if not ids:
        return
    hub.notify(tenant_id, event, {"title": title, "body": body}, user_ids=ids)
    subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(ids))).all()
    push.send_async([{"endpoint": s.endpoint, "p256dh": s.p256dh, "auth": s.auth} for s in subs],
                    title, body)


def changed(tenant_id: int, what: str = "shifts") -> None:
    """Sagt allen verbundenen Geräten der Firma, dass sie Daten neu laden sollen."""
    hub.notify(tenant_id, f"{what}.changed")
