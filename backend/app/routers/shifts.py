from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Shift, ShiftClaim, SwapRequest, User
from ..schemas import (ClaimDecision, ClaimOut, CopyWeekIn, PublishIn, ShiftCreate, ShiftOut,
                       ShiftUpdate)
from ..services.audit import audit
from ..services.rules import shift_warnings
from ..services.common import (changed, check_assignable, check_version, get_department_or_404,
                               get_user_or_404, has_leave, has_overlap, notify_users, permissions_for)
from ..utils import UTCDateTime, utcnow

router = APIRouter(prefix="/api/shifts", tags=["shifts"])


def _shift_or_404(db: Session, tenant_id: int, shift_id: int) -> Shift:
    s = db.get(Shift, shift_id)
    if not s or s.tenant_id != tenant_id or s.deleted_at:
        raise HTTPException(404, "Schicht nicht gefunden")
    return s


def _active_user(db: Session, tenant_id: int, user_id: int) -> User:
    u = get_user_or_404(db, tenant_id, user_id)
    if not u.is_active:
        raise HTTPException(422, "Dieser Benutzer ist deaktiviert")
    return u


def _warn(db, user: User, target_id: int, start, end, ignore: bool, exclude_id, break_minutes: int = 0) -> None:
    """Weiche Planungshinweise: 422 mit Liste, außer der Planer bestätigt ausdrücklich."""
    warnings = shift_warnings(db, user.tenant_id, target_id, start, end, exclude_id, break_minutes)
    if warnings and not ignore:
        raise HTTPException(422, detail={"message": "Planungshinweis: " + " ".join(warnings),
                                         "warnings": warnings})
    if warnings:
        audit(db, user, "shift.warning_ignored", f"user={target_id} {'; '.join(warnings)}"[:400])


def _outs(db: Session, tenant_id: int, shifts: list[Shift], manage: bool) -> list[ShiftOut]:
    uids = {s.user_id for s in shifts if s.user_id}
    names = {}
    if uids:
        names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(uids))).all()}
    pending: dict[int, int] = {}
    if manage and shifts:
        rows = db.execute(select(ShiftClaim.shift_id, func.count(ShiftClaim.id)).where(
            ShiftClaim.status == "pending", ShiftClaim.shift_id.in_([s.id for s in shifts]))
            .group_by(ShiftClaim.shift_id)).all()
        pending = {sid: n for sid, n in rows}
    return [ShiftOut(id=s.id, department_id=s.department_id, user_id=s.user_id,
                     user_name=names.get(s.user_id), start=s.start, end=s.end, note=s.note,
                     published=s.published, claim_requires_approval=s.claim_requires_approval, break_minutes=s.break_minutes,
                     pending_claims=pending.get(s.id, 0), version=s.version) for s in shifts]


@router.get("", response_model=list[ShiftOut])
def list_shifts(start: UTCDateTime, end: UTCDateTime, department_id: Optional[int] = None,
                user: User = Depends(require("shifts.view")), db: Session = Depends(get_db)):
    if end <= start or (end - start) > timedelta(days=93):
        raise HTTPException(422, "Zeitraum ungültig (maximal 93 Tage)")
    manage = "shifts.manage" in permissions_for(db, user)
    q = select(Shift).where(Shift.tenant_id == user.tenant_id, Shift.deleted_at.is_(None),
                            Shift.start < end, Shift.end > start)
    if department_id:
        q = q.where(Shift.department_id == department_id)
    if not manage:
        q = q.where(Shift.published.is_(True),
                    or_(Shift.user_id == user.id, Shift.department_id.in_(user.department_ids or [0])))
    shifts = db.scalars(q.order_by(Shift.start, Shift.id)).all()
    return _outs(db, user.tenant_id, list(shifts), manage)


@router.post("", response_model=ShiftOut, status_code=201)
def create_shift(body: ShiftCreate, request: Request, user: User = Depends(require("shifts.manage")),
                 db: Session = Depends(get_db)):
    get_department_or_404(db, user.tenant_id, body.department_id)
    if body.user_id:
        _active_user(db, user.tenant_id, body.user_id)
        check_assignable(db, user.tenant_id, body.user_id, body.start, body.end)
        _warn(db, user, body.user_id, body.start, body.end, body.ignore_warnings, None, body.break_minutes)
    s = Shift(tenant_id=user.tenant_id, department_id=body.department_id, user_id=body.user_id,
              start=body.start, end=body.end, note=body.note,
              claim_requires_approval=body.claim_requires_approval, break_minutes=body.break_minutes)
    db.add(s)
    db.flush()
    audit(db, user, "shift.create", f"shift={s.id}", request)
    db.commit()
    changed(user.tenant_id)
    return _outs(db, user.tenant_id, [s], True)[0]


@router.patch("/{shift_id}", response_model=ShiftOut)
def update_shift(shift_id: int, body: ShiftUpdate, request: Request,
                 user: User = Depends(require("shifts.manage")), db: Session = Depends(get_db)):
    s = _shift_or_404(db, user.tenant_id, shift_id)
    check_version(s, body.version)
    data = body.model_dump(exclude_unset=True)
    data.pop("version")
    ignore = bool(data.pop("ignore_warnings", False))
    for key in ("department_id", "start", "end", "note", "claim_requires_approval", "break_minutes"):
        if key in data and data[key] is None:
            data.pop(key)
    if "department_id" in data:
        get_department_or_404(db, user.tenant_id, data["department_id"])
    new_start, new_end = data.get("start", s.start), data.get("end", s.end)
    if new_end <= new_start or (new_end - new_start) > timedelta(hours=24):
        raise HTTPException(422, "Schichtzeiten ungültig")
    old_user, new_user = s.user_id, data.get("user_id", s.user_id)
    if new_user:
        _active_user(db, user.tenant_id, new_user)
        if (new_user != old_user or new_start != s.start or new_end != s.end
                or data.get("break_minutes", s.break_minutes) != s.break_minutes):
            check_assignable(db, user.tenant_id, new_user, new_start, new_end, exclude_id=s.id)
            _warn(db, user, new_user, new_start, new_end, ignore, s.id, data.get("break_minutes", s.break_minutes))
    time_changed = new_start != s.start or new_end != s.end
    for k, v in data.items():
        setattr(s, k, v)
    audit(db, user, "shift.update", f"shift={s.id} fields={','.join(sorted(data))}", request)
    db.commit()
    changed(user.tenant_id)
    if s.published:
        if new_user != old_user:
            notify_users(db, user.tenant_id, [old_user], "Schicht entfernt",
                         f"Deine Schicht am {s.start:%d.%m.%Y} wurde einer anderen Person zugeteilt.")
            notify_users(db, user.tenant_id, [new_user], "Neue Schicht",
                         f"Du wurdest für {s.start:%d.%m.%Y %H:%M} eingeteilt.")
        elif time_changed and new_user:
            notify_users(db, user.tenant_id, [new_user], "Schicht geändert",
                         f"Deine Schicht am {s.start:%d.%m.%Y} hat neue Zeiten.")
    return _outs(db, user.tenant_id, [s], True)[0]


@router.delete("/{shift_id}", status_code=204)
def delete_shift(shift_id: int, request: Request, user: User = Depends(require("shifts.manage")),
                 db: Session = Depends(get_db)):
    s = _shift_or_404(db, user.tenant_id, shift_id)
    s.deleted_at = utcnow()
    for sw in db.scalars(select(SwapRequest).where(SwapRequest.shift_id == s.id,
                                                   SwapRequest.status.in_(("open", "accepted")))).all():
        sw.status = "cancelled"
    for c in db.scalars(select(ShiftClaim).where(ShiftClaim.shift_id == s.id,
                                                 ShiftClaim.status == "pending")).all():
        c.status = "rejected"
    audit(db, user, "shift.delete", f"shift={s.id}", request)
    db.commit()
    changed(user.tenant_id)
    if s.published and s.user_id:
        notify_users(db, user.tenant_id, [s.user_id], "Schicht gestrichen",
                     f"Deine Schicht am {s.start:%d.%m.%Y} entfällt.")


@router.post("/publish")
def publish(body: PublishIn, request: Request, user: User = Depends(require("shifts.manage")),
            db: Session = Depends(get_db)):
    q = select(Shift).where(Shift.tenant_id == user.tenant_id, Shift.deleted_at.is_(None),
                            Shift.published.is_(False), Shift.start >= body.start, Shift.start < body.end)
    if body.department_id:
        q = q.where(Shift.department_id == body.department_id)
    shifts = db.scalars(q).all()
    for s in shifts:
        s.published = True
    audit(db, user, "shift.publish", f"count={len(shifts)} von={body.start} bis={body.end}", request)
    db.commit()
    changed(user.tenant_id)
    notify_users(db, user.tenant_id, [s.user_id for s in shifts], "Dienstplan veröffentlicht",
                 "Ein neuer Dienstplan ist verfügbar.")
    return {"published": len(shifts)}


@router.post("/copy-week")
def copy_week(body: CopyWeekIn, request: Request, user: User = Depends(require("shifts.manage")),
              db: Session = Depends(get_db)):
    from datetime import datetime as dt
    src_start = dt.combine(body.source_start, dt.min.time())
    src_end = src_start + timedelta(days=7)
    delta = dt.combine(body.target_start, dt.min.time()) - src_start
    if delta == timedelta(0):
        raise HTTPException(422, "Quell- und Zielwoche sind identisch")
    q = select(Shift).where(Shift.tenant_id == user.tenant_id, Shift.deleted_at.is_(None),
                            Shift.start >= src_start, Shift.start < src_end)
    if body.department_id:
        q = q.where(Shift.department_id == body.department_id)
    created, open_due_to_conflict = 0, 0
    for s in db.scalars(q).all():
        new_start, new_end = s.start + delta, s.end + delta
        uid = s.user_id if body.include_assignments else None
        if uid:
            u = db.get(User, uid)
            if (not u or not u.is_active or u.deleted_at
                    or has_overlap(db, user.tenant_id, uid, new_start, new_end)
                    or has_leave(db, user.tenant_id, uid, new_start, new_end)):
                uid = None
                open_due_to_conflict += 1
        db.add(Shift(tenant_id=user.tenant_id, department_id=s.department_id, user_id=uid,
                     start=new_start, end=new_end, note=s.note,
                     claim_requires_approval=s.claim_requires_approval, break_minutes=s.break_minutes))
        db.flush()  # damit spätere Überschneidungsprüfungen die neuen Schichten sehen
        created += 1
    audit(db, user, "shift.copy_week", f"{body.source_start} -> {body.target_start}, neu={created}", request)
    db.commit()
    changed(user.tenant_id)
    return {"created": created, "unassigned_due_to_conflict": open_due_to_conflict}


# ---------- Offene Schichten ----------
@router.post("/{shift_id}/claim")
def claim_shift(shift_id: int, request: Request, user: User = Depends(require("swap.request")),
                db: Session = Depends(get_db)):
    s = _shift_or_404(db, user.tenant_id, shift_id)
    if s.user_id is not None or not s.published:
        raise HTTPException(409, "Diese Schicht ist nicht offen")
    if s.department_id not in user.department_ids:
        raise HTTPException(403, "Diese Schicht gehört zu einer anderen Abteilung")
    if s.start <= utcnow():
        raise HTTPException(409, "Die Schicht hat bereits begonnen")
    check_assignable(db, user.tenant_id, user.id, s.start, s.end)
    if not s.claim_requires_approval:
        s.user_id = user.id
        audit(db, user, "shift.claim", f"shift={s.id} direkt übernommen", request)
        db.commit()
        changed(user.tenant_id)
        return {"status": "assigned"}
    if db.scalar(select(ShiftClaim.id).where(ShiftClaim.shift_id == s.id, ShiftClaim.user_id == user.id)):
        raise HTTPException(409, "Sie haben diese Schicht bereits angefragt")
    db.add(ShiftClaim(tenant_id=user.tenant_id, shift_id=s.id, user_id=user.id))
    audit(db, user, "shift.claim", f"shift={s.id} Anfrage", request)
    db.commit()
    changed(user.tenant_id)
    return {"status": "pending"}


@router.get("/{shift_id}/claims", response_model=list[ClaimOut])
def list_claims(shift_id: int, user: User = Depends(require("shifts.manage")), db: Session = Depends(get_db)):
    s = _shift_or_404(db, user.tenant_id, shift_id)
    rows = db.execute(select(ShiftClaim, User.name).join(User, User.id == ShiftClaim.user_id)
                      .where(ShiftClaim.shift_id == s.id).order_by(ShiftClaim.id)).all()
    return [ClaimOut(id=c.id, shift_id=c.shift_id, user_id=c.user_id, user_name=n, status=c.status)
            for c, n in rows]


@router.post("/claims/{claim_id}/decide")
def decide_claim(claim_id: int, body: ClaimDecision, request: Request,
                 user: User = Depends(require("shifts.manage")), db: Session = Depends(get_db)):
    c = db.get(ShiftClaim, claim_id)
    if not c or c.tenant_id != user.tenant_id:
        raise HTTPException(404, "Anfrage nicht gefunden")
    if c.status != "pending":
        raise HTTPException(409, "Die Anfrage wurde bereits entschieden")
    s = _shift_or_404(db, user.tenant_id, c.shift_id)
    if body.approve:
        if s.user_id is not None:
            raise HTTPException(409, "Die Schicht ist bereits besetzt")
        check_assignable(db, user.tenant_id, c.user_id, s.start, s.end)
        s.user_id = c.user_id
        c.status = "approved"
        for other in db.scalars(select(ShiftClaim).where(ShiftClaim.shift_id == s.id,
                                                         ShiftClaim.id != c.id,
                                                         ShiftClaim.status == "pending")).all():
            other.status = "rejected"
    else:
        c.status = "rejected"
    audit(db, user, "shift.claim_decide", f"claim={c.id} approve={body.approve}", request)
    db.commit()
    changed(user.tenant_id)
    notify_users(db, user.tenant_id, [c.user_id],
                 "Schicht zugeteilt" if body.approve else "Schicht abgelehnt",
                 f"Deine Anfrage für {s.start:%d.%m.%Y %H:%M} wurde {'angenommen' if body.approve else 'abgelehnt'}.")
    return {"status": c.status}
