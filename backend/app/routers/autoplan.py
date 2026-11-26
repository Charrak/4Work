"""Autoplaner: Schichtvorschlag und Stundenübersicht je Abrechnungszeitraum (Recht: shifts.manage)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import User
from ..schemas import AutoplanIn
from ..services import autoplan as svc
from ..services.audit import audit
from ..services.common import changed, get_department_or_404

router = APIRouter(prefix="/api/autoplan", tags=["autoplan"])


@router.post("")
def autoplan(body: AutoplanIn, request: Request, user: User = Depends(require("shifts.manage")),
             db: Session = Depends(get_db)):
    """Vorschau (apply=false, wird nicht gespeichert) oder Übernahme (apply=true, Schichten unveröffentlicht)."""
    tenant_id = user.tenant_id
    get_department_or_404(db, tenant_id, body.department_id)
    result = svc.run(db, tenant_id, body, dry_run=not body.apply)
    if body.apply:
        c = result["counts"]
        audit(db, user, "autoplan.apply",
              f"dept={body.department_id} {body.start}..{body.end} neu={c.get('created', 0)} "
              f"befuellt={c.get('filled_existing', 0)} offen={c.get('open_created', 0)} unbesetzt={c.get('unfilled', 0)}",
              request)
        db.commit()
        changed(tenant_id)
    return result


@router.get("/hours")
def hours(day: Optional[date] = None, department_id: Optional[int] = None, overtime_pct: float = 0.0,
          user: User = Depends(require("shifts.manage")), db: Session = Depends(get_db)):
    """Soll/Ziel/Max/geplant/Rest je Person im Abrechnungszeitraum, in dem `day` liegt (Standard: heute)."""
    from ..utils import to_local, utcnow
    if department_id:
        get_department_or_404(db, user.tenant_id, department_id)
    return svc.hours_overview(db, user.tenant_id, department_id, day or to_local(utcnow()).date(),
                              max(0.0, min(25.0, overtime_pct)))
