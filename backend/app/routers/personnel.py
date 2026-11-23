"""Personalakte: alles zu einer Person an einem Ort (nur mit Recht „Benutzer verwalten“).

Enthält Stammdaten, Vertragsdaten, Lohnverlauf, Urlaub/Krankheitstage, Dokumente, Arbeitszeit-Kennzahlen
und den Änderungsverlauf. Jeder Abruf wird protokolliert. Krankheitsgründe/Diagnosen werden nicht gespeichert;
es werden nur Anzahl Krankheitstage und die hochgeladenen Atteste gezeigt.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import AuditLog, Document, LeaveRequest, User, WageHistory
from ..services.audit import audit
from ..services.common import changed, check_version, get_user_or_404, permissions_for
from ..utils import utcnow, workdays
from .leave import _balance
from .reports import compute_summary
from .users import _admin_only

router = APIRouter(prefix="/api/personnel", tags=["personnel"])


class PersonnelIn(BaseModel):
    version: int
    phone: Optional[str] = Field(default=None, max_length=40)
    job_title: Optional[str] = Field(default=None, max_length=100)
    hire_date: Optional[date] = None
    contract_end: Optional[date] = None
    hr_note: Optional[str] = Field(default=None, max_length=4000)


def _clean(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return v or None


@router.get("/{user_id}")
def get_file(user_id: int, request: Request, user: User = Depends(require("users.manage")),
             db: Session = Depends(get_db)):
    t = get_user_or_404(db, user.tenant_id, user_id)
    _admin_only(user, t.role)
    year = date.today().year
    y0 = datetime(year, 1, 1)
    sick = vac = 0
    for r in db.scalars(select(LeaveRequest).where(
            LeaveRequest.user_id == t.id, LeaveRequest.status == "approved",
            LeaveRequest.start_date >= date(year, 1, 1), LeaveRequest.start_date <= date(year, 12, 31))).all():
        days = workdays(r.start_date, r.end_date, t.work_days)
        if r.kind == "sick":
            sick += days
        elif r.kind == "vacation":
            vac += days
    bal = _balance(db, t, year)
    row = next((x for x in compute_summary(db, user.tenant_id, y0, utcnow()).get("rows", [])
                if x["user_id"] == t.id), {})
    # Dokumente (Verträge, Atteste = Gesundheitsdaten) nur mit zusätzlichem Recht „documents.manage“
    docs = []
    if "documents.manage" in permissions_for(db, user):
        docs = db.scalars(select(Document).where(Document.user_id == t.id, Document.deleted_at.is_(None))
                          .order_by(Document.created_at.desc())).all()
    wages = db.scalars(select(WageHistory).where(WageHistory.user_id == t.id)
                       .order_by(WageHistory.valid_from.desc(), WageHistory.id.desc())).all()
    needle = f"user={t.id}"
    events = db.scalars(select(AuditLog).where(
        AuditLog.tenant_id == user.tenant_id,
        or_(AuditLog.detail.like(f"{needle} %"), AuditLog.detail == needle)
    ).order_by(AuditLog.id.desc()).limit(40)).all()
    audit(db, user, "personnel.view", f"user={t.id}", request)
    db.commit()
    return {
        "profile": {
            "id": t.id, "version": t.version, "name": t.name, "email": t.email, "role": t.role,
            "is_active": t.is_active, "department_ids": t.department_ids, "created_at": t.created_at.isoformat() + "Z",
            "phone": t.phone, "job_title": t.job_title,
            "hire_date": t.hire_date.isoformat() if t.hire_date else None,
            "contract_end": t.contract_end.isoformat() if t.contract_end else None,
            "hr_note": t.hr_note,
        },
        "contract": {
            "weekly_hours": t.weekly_hours, "work_days": t.work_days, "vacation_days": t.vacation_days,
            "hourly_rate": t.hourly_rate, "is_minor": bool(t.is_minor), "is_minijob": bool(t.is_minijob),
            "minijob_limit": t.minijob_limit,
        },
        "wages": [{"id": w.id, "hourly_rate": w.hourly_rate, "valid_from": w.valid_from.isoformat()} for w in wages],
        "year": year,
        "leave": {"entitlement": bal.entitlement, "used": bal.used, "pending": bal.pending, "remaining": bal.remaining,
                  "vacation_days_taken": vac, "sick_days": sick},
        "time": {k: row.get(k) for k in ("worked_hours", "planned_hours", "overtime_hours", "night_hours",
                                         "sunday_hours", "holiday_hours", "gross_cost", "over_limit_days",
                                         "over_limit_weeks", "avg_weekly_hours_26w", "minijob_months_over")},
        "documents": [{"id": d.id, "category": d.category, "title": d.title, "filename": d.filename,
                       "size": d.size, "created_at": d.created_at.isoformat() + "Z"} for d in docs],
        "history": [{"id": e.id, "action": e.action, "detail": e.detail, "created_at": e.created_at.isoformat() + "Z"}
                    for e in events],
    }


@router.put("/{user_id}")
def update_file(user_id: int, body: PersonnelIn, request: Request, user: User = Depends(require("users.manage")),
                db: Session = Depends(get_db)):
    t = get_user_or_404(db, user.tenant_id, user_id)
    _admin_only(user, t.role)
    check_version(t, body.version)
    if body.hire_date and body.contract_end and body.contract_end < body.hire_date:
        raise HTTPException(422, "Das Vertragsende liegt vor dem Eintrittsdatum")
    t.phone, t.job_title, t.hr_note = _clean(body.phone), _clean(body.job_title), _clean(body.hr_note)
    t.hire_date, t.contract_end = body.hire_date, body.contract_end
    audit(db, user, "personnel.update", f"user={t.id} felder=telefon,funktion,eintritt,vertragsende,notiz", request)
    db.commit()
    changed(user.tenant_id, "users")
    return {"ok": True, "version": t.version}
