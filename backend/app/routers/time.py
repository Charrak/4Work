from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require
from ..models import Shift, TimeEntry, User
from ..schemas import ClockIn, TimeEntryOut, TimeEntryUpdate
from ..services.audit import audit
from ..services.common import changed, permissions_for
from ..services.limits import get_limit
from ..utils import to_local
from ..utils import UTCDateTime, utcnow

router = APIRouter(prefix="/api/time", tags=["time"])


def _out(e: TimeEntry, name: str) -> TimeEntryOut:
    minutes = int((e.clock_out - e.clock_in).total_seconds() // 60) if e.clock_out else None
    return TimeEntryOut(id=e.id, user_id=e.user_id, user_name=name, shift_id=e.shift_id,
                        clock_in=e.clock_in, clock_out=e.clock_out, minutes=minutes,
                        approved=e.approved, note=e.note)


def _clock_warnings(db: Session, user: User, now) -> list[str]:
    """Prüft vor dem Einstempeln Ruhezeit sowie Tages-/Wochenhöchstarbeitszeit (netto, Pausen nicht bekannt)."""
    from ..routers.reports import legal_break_minutes
    max_day, max_week = get_limit(db, user.tenant_id, "max_daily_hours"), get_limit(db, user.tenant_id, "max_weekly_hours")
    min_rest = 11
    if user.is_minor:
        max_day, max_week, min_rest = 8.0, 40.0, 12
    out: list[str] = []
    local_today = to_local(now).date()
    week_start = local_today - timedelta(days=local_today.weekday())
    entries = db.scalars(select(TimeEntry).where(
        TimeEntry.user_id == user.id, TimeEntry.clock_out.is_not(None),
        TimeEntry.clock_in >= now - timedelta(days=8))).all()
    day_h = week_h = 0.0
    last_out = None
    for e in entries:
        gm = (e.clock_out - e.clock_in).total_seconds() / 60
        h = max(0.0, gm - legal_break_minutes(gm, bool(user.is_minor))) / 60
        d = to_local(e.clock_in).date()
        if d == local_today:
            day_h += h
        if week_start <= d < week_start + timedelta(days=7):
            week_h += h
        if last_out is None or e.clock_out > last_out:
            last_out = e.clock_out
    if last_out and (now - last_out).total_seconds() / 3600 < min_rest:
        out.append(f"Ruhezeit unter {min_rest} Stunden seit dem letzten Ausstempeln")
    if day_h >= max_day:
        out.append(f"Die Höchstarbeitszeit von {max_day:g} Stunden pro Tag ist heute bereits erreicht")
    if week_h >= max_week:
        out.append(f"Die Höchstarbeitszeit von {max_week:g} Stunden pro Woche ist bereits erreicht")
    return out


def _open_entry(db: Session, user: User) -> Optional[TimeEntry]:
    return db.scalar(select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.clock_out.is_(None)))


@router.get("/status")
def status(user: User = Depends(require("time.clock")), db: Session = Depends(get_db)):
    e = _open_entry(db, user)
    return {"clocked_in": e is not None, "entry": _out(e, user.name) if e else None}


@router.post("/clock-in", response_model=TimeEntryOut, status_code=201)
def clock_in(body: ClockIn, request: Request, user: User = Depends(require("time.clock")),
             db: Session = Depends(get_db)):
    if _open_entry(db, user):
        raise HTTPException(409, "Sie sind bereits eingestempelt")
    now = utcnow()
    shift = None
    if body.shift_id:
        shift = db.get(Shift, body.shift_id)
        if not shift or shift.tenant_id != user.tenant_id or shift.user_id != user.id or shift.deleted_at:
            raise HTTPException(404, "Schicht nicht gefunden")
    else:  # passende Schicht automatisch finden (2 Stunden Toleranz vor Beginn)
        cands = db.scalars(select(Shift).where(
            Shift.tenant_id == user.tenant_id, Shift.user_id == user.id, Shift.deleted_at.is_(None),
            Shift.published.is_(True), Shift.start <= now + timedelta(hours=2), Shift.end >= now)
            .order_by(Shift.start)).all()
        shift = cands[0] if cands else None
    warnings = _clock_warnings(db, user, now)
    if warnings:
        if get_limit(db, user.tenant_id, "block_clock_over_limit") >= 1:
            raise HTTPException(422, detail={"message": "Einstempeln nicht möglich: " + " ".join(warnings)
                                             + " Bitte wenden Sie sich an die Leitung.", "warnings": warnings})
        audit(db, user, "time.limit_warning", " | ".join(warnings)[:400], request)
    # Standort wird nur gespeichert, wenn die Person ausdrücklich zugestimmt hat
    lat, lon = (body.lat, body.lon) if body.consent_location else (None, None)
    e = TimeEntry(tenant_id=user.tenant_id, user_id=user.id, shift_id=shift.id if shift else None,
                  clock_in=now, lat=lat, lon=lon)
    db.add(e)
    db.flush()
    audit(db, user, "time.clock_in", f"entry={e.id}", request)
    db.commit()
    changed(user.tenant_id, "time")
    return _out(e, user.name)


@router.post("/clock-out", response_model=TimeEntryOut)
def clock_out(request: Request, user: User = Depends(require("time.clock")), db: Session = Depends(get_db)):
    e = _open_entry(db, user)
    if not e:
        raise HTTPException(409, "Sie sind nicht eingestempelt")
    e.clock_out = utcnow()
    audit(db, user, "time.clock_out", f"entry={e.id}", request)
    db.commit()
    changed(user.tenant_id, "time")
    return _out(e, user.name)


@router.get("/entries", response_model=list[TimeEntryOut])
def entries(start: UTCDateTime, end: UTCDateTime, user_id: Optional[int] = None, all: bool = False,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    can_approve = "time.approve" in permissions_for(db, user)
    q = select(TimeEntry, User.name).join(User, User.id == TimeEntry.user_id).where(
        TimeEntry.tenant_id == user.tenant_id, TimeEntry.clock_in >= start, TimeEntry.clock_in < end)
    if user_id and user_id != user.id:
        if not can_approve:
            raise HTTPException(403, "Keine Berechtigung")
        q = q.where(TimeEntry.user_id == user_id)
    elif not (all and can_approve):
        q = q.where(TimeEntry.user_id == user.id)
    return [_out(e, n) for e, n in db.execute(q.order_by(TimeEntry.clock_in.desc()).limit(1000)).all()]


@router.patch("/entries/{entry_id}", response_model=TimeEntryOut)
def edit_entry(entry_id: int, body: TimeEntryUpdate, request: Request,
               user: User = Depends(require("time.approve")), db: Session = Depends(get_db)):
    e = db.get(TimeEntry, entry_id)
    if not e or e.tenant_id != user.tenant_id:
        raise HTTPException(404, "Eintrag nicht gefunden")
    before = f"in={e.clock_in} out={e.clock_out} approved={e.approved}"
    data = body.model_dump(exclude_unset=True)
    if data.get("clock_in"):
        e.clock_in = data["clock_in"]
    if "clock_out" in data:
        e.clock_out = data["clock_out"]
    if data.get("note") is not None:
        e.note = data["note"]
    if data.get("approved") is not None:
        e.approved = data["approved"]
    if e.clock_out and e.clock_out <= e.clock_in:
        db.rollback()
        raise HTTPException(422, "Das Ende muss nach dem Beginn liegen")
    audit(db, user, "time.edit", f"entry={e.id} vorher: {before}", request)
    db.commit()
    changed(user.tenant_id, "time")
    return _out(e, db.get(User, e.user_id).name)
