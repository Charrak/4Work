"""Verfügbarkeiten: wiederkehrende Zeiten, an denen eine Person nicht eingeplant werden kann.

Jede Person pflegt ihre eigenen Angaben. Planer (shifts.manage) sehen alle und bekommen
beim Einplanen einen Hinweis (siehe services/rules.py). Es sind nur Hinweise, keine Sperren.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require
from ..models import Availability
from ..schemas import AvailabilityListIn, AvailabilityOut
from ..services.audit import audit
from ..services.common import changed, get_user_or_404, permissions_for

router = APIRouter(prefix="/api/availability", tags=["availability"])


@router.get("", response_model=list[AvailabilityOut])
def list_availability(user_id: Optional[int] = None, user=Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Ohne user_id: eigene Angaben. Mit user_id (oder alle=Planer): nur mit Recht shifts.manage."""
    q = select(Availability).where(Availability.tenant_id == user.tenant_id)
    if user_id is not None and user_id != user.id:
        if "shifts.manage" not in permissions_for(db, user):
            raise HTTPException(403, "Keine Berechtigung")
        get_user_or_404(db, user.tenant_id, user_id)
    q = q.where(Availability.user_id == (user_id if user_id is not None else user.id))
    return db.scalars(q.order_by(Availability.weekday, Availability.start_time)).all()


@router.get("/all", response_model=list[AvailabilityOut])
def list_all(user=Depends(require("shifts.manage")), db: Session = Depends(get_db)):
    return db.scalars(select(Availability).where(Availability.tenant_id == user.tenant_id)
                      .order_by(Availability.user_id, Availability.weekday, Availability.start_time)).all()


@router.put("", response_model=list[AvailabilityOut])
def replace_own(body: AvailabilityListIn, request: Request, user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Ersetzt die eigene Liste vollständig (einfach und konfliktfrei bei mehreren Geräten)."""
    db.execute(delete(Availability).where(Availability.user_id == user.id))
    rows = [Availability(tenant_id=user.tenant_id, user_id=user.id, **i.model_dump()) for i in body.items]
    db.add_all(rows)
    db.flush()
    audit(db, user, "availability.update", f"anzahl={len(rows)}", request)
    db.commit()
    changed(user.tenant_id, "availability")
    return rows
