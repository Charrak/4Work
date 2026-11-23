from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import ShiftTemplate, User
from ..schemas import TemplateIn, TemplateOut
from ..services.audit import audit
from ..services.common import get_department_or_404

router = APIRouter(prefix="/api/shift-templates", tags=["templates"])


def _get(db: Session, tenant_id: int, tid: int) -> ShiftTemplate:
    t = db.get(ShiftTemplate, tid)
    if not t or t.tenant_id != tenant_id:
        raise HTTPException(404, "Vorlage nicht gefunden")
    return t


@router.get("", response_model=list[TemplateOut])
def list_templates(user: User = Depends(require("shifts.view")), db: Session = Depends(get_db)):
    return db.scalars(select(ShiftTemplate).where(ShiftTemplate.tenant_id == user.tenant_id)
                      .order_by(ShiftTemplate.name)).all()


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateIn, request: Request, user: User = Depends(require("shifts.manage")),
                    db: Session = Depends(get_db)):
    if body.department_id:
        get_department_or_404(db, user.tenant_id, body.department_id)
    t = ShiftTemplate(tenant_id=user.tenant_id, **body.model_dump())
    db.add(t)
    db.flush()
    audit(db, user, "template.create", f"template={t.id}", request)
    db.commit()
    return t


@router.put("/{tid}", response_model=TemplateOut)
def update_template(tid: int, body: TemplateIn, request: Request,
                    user: User = Depends(require("shifts.manage")), db: Session = Depends(get_db)):
    t = _get(db, user.tenant_id, tid)
    if body.department_id:
        get_department_or_404(db, user.tenant_id, body.department_id)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    audit(db, user, "template.update", f"template={t.id}", request)
    db.commit()
    return t


@router.delete("/{tid}", status_code=204)
def delete_template(tid: int, request: Request, user: User = Depends(require("shifts.manage")),
                    db: Session = Depends(get_db)):
    t = _get(db, user.tenant_id, tid)
    db.delete(t)
    audit(db, user, "template.delete", f"template={tid}", request)
    db.commit()
