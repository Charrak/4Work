from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require
from ..models import LeaveRequest, User
from ..schemas import AbsenceOut, LeaveBalance, LeaveCreate, LeaveDecision, LeaveOut
from ..services.audit import audit
from ..services.common import changed, get_user_or_404, notify_users, permissions_for
from ..utils import workdays

router = APIRouter(prefix="/api/leave", tags=["leave"])


def _used(db: Session, user: User, year: int, statuses: tuple) -> int:
    rows = db.scalars(select(LeaveRequest).where(
        LeaveRequest.user_id == user.id, LeaveRequest.kind == "vacation",
        LeaveRequest.status.in_(statuses))).all()
    return sum(workdays(r.start_date, r.end_date, user.work_days) for r in rows if r.start_date.year == year)


def _balance(db: Session, user: User, year: int) -> LeaveBalance:
    used = _used(db, user, year, ("approved",))
    pending = _used(db, user, year, ("pending",))
    return LeaveBalance(user_id=user.id, year=year, entitlement=user.vacation_days, used=used,
                        pending=pending, remaining=user.vacation_days - used - pending)


def _out(r: LeaveRequest, name: str, wd: str = "12345") -> LeaveOut:
    return LeaveOut(id=r.id, user_id=r.user_id, user_name=name, start_date=r.start_date,
                    end_date=r.end_date, days=workdays(r.start_date, r.end_date, wd), kind=r.kind, note=r.note,
                    status=r.status, decision_comment=r.decision_comment)


@router.post("", response_model=LeaveOut, status_code=201)
def create_leave(body: LeaveCreate, request: Request, user: User = Depends(require("leave.request")),
                 db: Session = Depends(get_db)):
    if body.kind != "sick" and body.start_date < date.today():
        raise HTTPException(422, "Rückwirkend kann nur eine Krankmeldung erfasst werden")
    clash = db.scalar(select(LeaveRequest.id).where(
        LeaveRequest.user_id == user.id, LeaveRequest.status.in_(("pending", "approved")),
        LeaveRequest.start_date <= body.end_date, LeaveRequest.end_date >= body.start_date))
    if clash:
        raise HTTPException(409, "Für diesen Zeitraum existiert bereits ein Antrag")
    days = workdays(body.start_date, body.end_date, user.work_days)
    if days == 0:
        raise HTTPException(422, "Der Zeitraum enthält keinen Arbeitstag (freier Tag/Wochenende/Feiertag)")
    if body.kind == "vacation":
        bal = _balance(db, user, body.start_date.year)
        if days > bal.remaining:
            raise HTTPException(409, f"Das Urlaubskonto reicht nicht aus (verbleibend: {bal.remaining} Tage)")
    r = LeaveRequest(tenant_id=user.tenant_id, user_id=user.id, start_date=body.start_date,
                     end_date=body.end_date, kind=body.kind, note=body.note)
    db.add(r)
    db.flush()
    audit(db, user, "leave.create", f"leave={r.id} art={r.kind}", request)
    db.commit()
    changed(user.tenant_id, "leave")
    return _out(r, user.name, user.work_days)


@router.get("", response_model=list[LeaveOut])
def list_leave(all: bool = False, status: Optional[str] = None,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    can_all = "leave.approve" in permissions_for(db, user)
    q = select(LeaveRequest, User.name, User.work_days).join(User, User.id == LeaveRequest.user_id).where(
        LeaveRequest.tenant_id == user.tenant_id)
    if not (all and can_all):
        q = q.where(LeaveRequest.user_id == user.id)
    if status:
        q = q.where(LeaveRequest.status == status)
    return [_out(r, n, w) for r, n, w in db.execute(q.order_by(LeaveRequest.start_date.desc()).limit(500)).all()]


@router.get("/balance", response_model=LeaveBalance)
def balance(user_id: Optional[int] = None, year: Optional[int] = None,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = user
    if user_id and user_id != user.id:
        if "leave.approve" not in permissions_for(db, user):
            raise HTTPException(403, "Keine Berechtigung")
        target = get_user_or_404(db, user.tenant_id, user_id)
    return _balance(db, target, year or date.today().year)


@router.get("/absences", response_model=list[AbsenceOut])
def absences(start: date, end: date, user: User = Depends(require("shifts.view")),
             db: Session = Depends(get_db)):
    """Wer ist abwesend? Kollegen sehen nur "abwesend" (ohne Grund), Genehmiger sehen die Art."""
    if end < start or (end - start).days > 93:
        raise HTTPException(422, "Zeitraum ungültig (maximal 93 Tage)")
    manage = "leave.approve" in permissions_for(db, user)
    rows = db.execute(select(LeaveRequest, User).join(User, User.id == LeaveRequest.user_id).where(
        LeaveRequest.tenant_id == user.tenant_id, LeaveRequest.status == "approved",
        LeaveRequest.start_date <= end, LeaveRequest.end_date >= start,
        User.deleted_at.is_(None)).order_by(LeaveRequest.start_date)).all()
    mine = set(user.department_ids)
    out = []
    for r, u in rows:
        if not manage and u.id != user.id and not (mine & set(u.department_ids)):
            continue
        shown = r.kind if (manage or u.id == user.id) else "absent"
        out.append(AbsenceOut(user_id=u.id, user_name=u.name, start_date=r.start_date,
                              end_date=r.end_date, kind=shown))
    return out


@router.post("/{leave_id}/decide", response_model=LeaveOut)
def decide(leave_id: int, body: LeaveDecision, request: Request,
           user: User = Depends(require("leave.approve")), db: Session = Depends(get_db)):
    r = db.get(LeaveRequest, leave_id)
    if not r or r.tenant_id != user.tenant_id:
        raise HTTPException(404, "Antrag nicht gefunden")
    if r.user_id == user.id:
        raise HTTPException(403, "Eigene Anträge können nicht selbst entschieden werden")
    if r.status != "pending":
        raise HTTPException(409, "Der Antrag wurde bereits entschieden")
    r.status = "approved" if body.approve else "rejected"
    r.decided_by = user.id
    r.decision_comment = body.comment
    audit(db, user, "leave.decide", f"leave={r.id} approve={body.approve}", request)
    db.commit()
    changed(user.tenant_id, "leave")
    notify_users(db, user.tenant_id, [r.user_id],
                 "Urlaub genehmigt" if body.approve else "Urlaub abgelehnt",
                 f"Dein Urlaub {r.start_date:%d.%m.%Y} bis {r.end_date:%d.%m.%Y} wurde "
                 f"{'genehmigt' if body.approve else 'abgelehnt'}.")
    _u = db.get(User, r.user_id)
    return _out(r, _u.name, _u.work_days)


@router.post("/{leave_id}/cancel", response_model=LeaveOut)
def cancel(leave_id: int, request: Request, user: User = Depends(require("leave.request")),
           db: Session = Depends(get_db)):
    r = db.get(LeaveRequest, leave_id)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Antrag nicht gefunden")
    if r.status not in ("pending", "approved") or r.start_date <= date.today():
        raise HTTPException(409, "Dieser Antrag kann nicht mehr storniert werden")
    r.status = "cancelled"
    audit(db, user, "leave.cancel", f"leave={r.id}", request)
    db.commit()
    changed(user.tenant_id, "leave")
    return _out(r, user.name, user.work_days)
