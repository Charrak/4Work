from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Shift, SwapRequest, User
from ..schemas import SwapCreate, SwapDecision, SwapOut
from ..services.audit import audit
from ..services.common import (changed, check_assignable, get_user_or_404, notify_users,
                               permissions_for)
from ..utils import utcnow

router = APIRouter(prefix="/api/swaps", tags=["swaps"])


def _out(db: Session, sw: SwapRequest) -> SwapOut:
    shift = db.get(Shift, sw.shift_id)
    frm = db.get(User, sw.from_user_id)
    to = db.get(User, sw.to_user_id) if sw.to_user_id else None
    return SwapOut(id=sw.id, shift_id=sw.shift_id, department_id=shift.department_id,
                   shift_start=shift.start, shift_end=shift.end, from_user_id=sw.from_user_id,
                   from_user_name=frm.name, to_user_id=sw.to_user_id,
                   to_user_name=to.name if to else None, status=sw.status)


def _swap_or_404(db: Session, tenant_id: int, swap_id: int) -> SwapRequest:
    sw = db.get(SwapRequest, swap_id)
    if not sw or sw.tenant_id != tenant_id:
        raise HTTPException(404, "Tauschanfrage nicht gefunden")
    return sw


@router.post("", response_model=SwapOut, status_code=201)
def create_swap(body: SwapCreate, request: Request, user: User = Depends(require("swap.request")),
                db: Session = Depends(get_db)):
    shift = db.get(Shift, body.shift_id)
    if not shift or shift.tenant_id != user.tenant_id or shift.deleted_at:
        raise HTTPException(404, "Schicht nicht gefunden")
    if shift.user_id != user.id:
        raise HTTPException(403, "Sie können nur eigene Schichten tauschen")
    if not shift.published or shift.start <= utcnow():
        raise HTTPException(409, "Diese Schicht kann nicht mehr getauscht werden")
    if db.scalar(select(SwapRequest.id).where(SwapRequest.shift_id == shift.id,
                                              SwapRequest.status.in_(("open", "accepted")))):
        raise HTTPException(409, "Für diese Schicht läuft bereits eine Tauschanfrage")
    if body.to_user_id is not None:
        target = get_user_or_404(db, user.tenant_id, body.to_user_id)
        if target.id == user.id or not target.is_active or shift.department_id not in target.department_ids:
            raise HTTPException(422, "Diese Person kann die Schicht nicht übernehmen")
    sw = SwapRequest(tenant_id=user.tenant_id, shift_id=shift.id, from_user_id=user.id,
                     to_user_id=body.to_user_id)
    db.add(sw)
    db.flush()
    audit(db, user, "swap.create", f"swap={sw.id} shift={shift.id}", request)
    db.commit()
    changed(user.tenant_id, "swaps")
    if body.to_user_id:
        recipients = [body.to_user_id]
    else:
        recipients = [u.id for u in db.scalars(select(User).where(
            User.tenant_id == user.tenant_id, User.is_active.is_(True), User.deleted_at.is_(None),
            User.id != user.id)).all() if shift.department_id in u.department_ids]
    notify_users(db, user.tenant_id, recipients, "Schichttausch angefragt",
                 f"{user.name} sucht Ersatz für {shift.start:%d.%m.%Y %H:%M}.", "swaps.changed")
    return _out(db, sw)


@router.get("", response_model=list[SwapOut])
def list_swaps(user: User = Depends(require("shifts.view")), db: Session = Depends(get_db)):
    manage = "shifts.manage" in permissions_for(db, user)
    q = select(SwapRequest).where(SwapRequest.tenant_id == user.tenant_id)
    if manage:
        q = q.where(or_(SwapRequest.status.in_(("open", "accepted")),
                        SwapRequest.from_user_id == user.id, SwapRequest.to_user_id == user.id))
    else:
        q = q.where(or_(SwapRequest.from_user_id == user.id, SwapRequest.to_user_id == user.id,
                        (SwapRequest.status == "open")))
    result = []
    for sw in db.scalars(q.order_by(SwapRequest.id.desc()).limit(200)).all():
        shift = db.get(Shift, sw.shift_id)
        mine = user.id in (sw.from_user_id, sw.to_user_id)
        open_for_me = (sw.status == "open" and sw.to_user_id is None
                       and shift.department_id in user.department_ids)
        if manage or mine or open_for_me:
            result.append(_out(db, sw))
    return result


@router.post("/{swap_id}/accept", response_model=SwapOut)
def accept_swap(swap_id: int, request: Request, user: User = Depends(require("swap.request")),
                db: Session = Depends(get_db)):
    sw = _swap_or_404(db, user.tenant_id, swap_id)
    shift = db.get(Shift, sw.shift_id)
    if sw.status != "open":
        raise HTTPException(409, "Diese Anfrage ist nicht mehr offen")
    if sw.from_user_id == user.id:
        raise HTTPException(400, "Sie können Ihre eigene Anfrage nicht annehmen")
    if sw.to_user_id and sw.to_user_id != user.id:
        raise HTTPException(403, "Diese Anfrage richtet sich an eine andere Person")
    if shift.department_id not in user.department_ids:
        raise HTTPException(403, "Diese Schicht gehört zu einer anderen Abteilung")
    check_assignable(db, user.tenant_id, user.id, shift.start, shift.end)
    sw.to_user_id = user.id
    sw.status = "accepted"
    audit(db, user, "swap.accept", f"swap={sw.id}", request)
    db.commit()
    changed(user.tenant_id, "swaps")
    notify_users(db, user.tenant_id, [sw.from_user_id], "Tausch angenommen",
                 f"{user.name} übernimmt deine Schicht. Es fehlt nur noch die Freigabe.")
    return _out(db, sw)


@router.post("/{swap_id}/decide", response_model=SwapOut)
def decide_swap(swap_id: int, body: SwapDecision, request: Request,
                user: User = Depends(require("shifts.manage")), db: Session = Depends(get_db)):
    sw = _swap_or_404(db, user.tenant_id, swap_id)
    if sw.status != "accepted":
        raise HTTPException(409, "Nur angenommene Tauschanfragen können freigegeben werden")
    shift = db.get(Shift, sw.shift_id)
    if shift.deleted_at or shift.user_id != sw.from_user_id:
        sw.status = "cancelled"
        db.commit()
        raise HTTPException(409, "Die Schicht wurde zwischenzeitlich geändert; Anfrage storniert")
    if body.approve:
        check_assignable(db, user.tenant_id, sw.to_user_id, shift.start, shift.end)
        shift.user_id = sw.to_user_id
        sw.status = "approved"
    else:
        sw.status = "rejected"
    audit(db, user, "swap.decide", f"swap={sw.id} approve={body.approve}", request)
    db.commit()
    changed(user.tenant_id)
    changed(user.tenant_id, "swaps")
    txt = "genehmigt" if body.approve else "abgelehnt"
    notify_users(db, user.tenant_id, [sw.from_user_id, sw.to_user_id], f"Tausch {txt}",
                 f"Der Schichttausch am {shift.start:%d.%m.%Y} wurde {txt}.")
    return _out(db, sw)


@router.post("/{swap_id}/cancel", response_model=SwapOut)
def cancel_swap(swap_id: int, request: Request, user: User = Depends(require("swap.request")),
                db: Session = Depends(get_db)):
    sw = _swap_or_404(db, user.tenant_id, swap_id)
    if sw.from_user_id != user.id:
        raise HTTPException(403, "Nur die anfragende Person kann stornieren")
    if sw.status not in ("open", "accepted"):
        raise HTTPException(409, "Diese Anfrage kann nicht mehr storniert werden")
    sw.status = "cancelled"
    audit(db, user, "swap.cancel", f"swap={sw.id}", request)
    db.commit()
    changed(user.tenant_id, "swaps")
    return _out(db, sw)
