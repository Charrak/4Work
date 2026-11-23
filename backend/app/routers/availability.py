"""Verfügbarkeiten: wiederkehrende Zeiten, an denen eine Person nicht eingeplant werden kann.

Jede Person pflegt ihre eigenen Angaben. Administratoren und Rollen mit dem Recht availability.manage (Standard: Planer-Rolle; entziehbar,
normale Mitarbeiter haben es nie) sehen die Angaben anderer und können sie pflegen (z. B. für Mitarbeiter ohne Smartphone).
Wer das Recht nicht hat, erhält beim Einplanen nur einen Hinweis ohne Begründungstext (siehe services/rules.py). Es sind nur Hinweise, keine Sperren.
Einträge gelten wöchentlich (weekday) oder nur für einen einzelnen Tag (on_date).
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
    """Ohne user_id: eigene Angaben. Mit user_id (oder alle): nur mit Recht availability.manage."""
    q = select(Availability).where(Availability.tenant_id == user.tenant_id)
    if user_id is not None and user_id != user.id:
        if "availability.manage" not in permissions_for(db, user):
            raise HTTPException(403, "Keine Berechtigung")
        get_user_or_404(db, user.tenant_id, user_id)
    q = q.where(Availability.user_id == (user_id if user_id is not None else user.id))
    return db.scalars(q.order_by(Availability.on_date.is_not(None), Availability.on_date, Availability.weekday, Availability.start_time)).all()


@router.get("/all", response_model=list[AvailabilityOut])
def list_all(user=Depends(require("availability.manage")), db: Session = Depends(get_db)):
    return db.scalars(select(Availability).where(Availability.tenant_id == user.tenant_id)
                      .order_by(Availability.user_id, Availability.weekday, Availability.start_time)).all()


@router.put("", response_model=list[AvailabilityOut])
def replace(body: AvailabilityListIn, request: Request, user_id: Optional[int] = None,
            user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Ersetzt die Liste vollständig (einfach und konfliktfrei bei mehreren Geräten).
    Ohne user_id: eigene Liste. Mit user_id einer anderen Person: nur mit Recht availability.manage (wird protokolliert)."""
    target = user
    if user_id is not None and user_id != user.id:
        if "availability.manage" not in permissions_for(db, user):
            raise HTTPException(403, "Keine Berechtigung")
        target = get_user_or_404(db, user.tenant_id, user_id)
    db.execute(delete(Availability).where(Availability.user_id == target.id,
                                          Availability.tenant_id == user.tenant_id))
    rows = [Availability(tenant_id=user.tenant_id, user_id=target.id, **i.model_dump()) for i in body.items]
    db.add_all(rows)
    db.flush()
    audit(db, user, "availability.update",
          f"anzahl={len(rows)}" + (f" fuer_user={target.id}" if target.id != user.id else ""), request)
    db.commit()
    changed(user.tenant_id, "availability")
    return rows
