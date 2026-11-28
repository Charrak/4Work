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

# Abweichung Soll/Ist (Minuten), ab der eine Freigabe nur mit Kontrollvermerk möglich ist (wie in der App)
DEVIATION_LIMIT_MIN = 30


def deviation_reason(db: Session, e: TimeEntry) -> Optional[str]:
    """Grund, warum der Eintrag einzeln geprüft werden muss, sonst None."""
    if not e.clock_out:
        return None
    s = db.get(Shift, e.shift_id) if e.shift_id else None
    if not s or s.deleted_at:
        return "ohne geplante Schicht gestempelt"
    from .reports import effective_break
    mins = lambda a, b: round((b - a).total_seconds() / 60)  # noqa: E731  (wie in der App: ganze Minuten)
    gross = mins(e.clock_in, e.clock_out)
    minor = bool(getattr(db.get(User, e.user_id), "is_minor", False))
    soll = max(0.0, mins(s.start, s.end) - s.break_minutes)
    ist = max(0.0, gross - effective_break(e, s.break_minutes, gross, minor))
    if abs(ist - soll) > DEVIATION_LIMIT_MIN:
        return f"Arbeitszeit weicht um {round(ist - soll)} Minuten vom Soll ab"
    if abs(mins(s.start, e.clock_in)) > DEVIATION_LIMIT_MIN or abs(mins(s.end, e.clock_out)) > DEVIATION_LIMIT_MIN:
        return "Kommen/Gehen weicht mehr als 30 Minuten von der Schicht ab"
    return None


def _out(e: TimeEntry, name: str) -> TimeEntryOut:
    minutes = int((e.clock_out - e.clock_in).total_seconds() // 60) if e.clock_out else None
    return TimeEntryOut(id=e.id, user_id=e.user_id, user_name=name, shift_id=e.shift_id,
                        clock_in=e.clock_in, clock_out=e.clock_out, minutes=minutes,
                        approved=e.approved, note=e.note, break_start=e.break_start,
                        break_taken_min=e.break_taken_min, orig_clock_in=e.orig_clock_in,
                        orig_clock_out=e.orig_clock_out, edited_at=e.edited_at, edited_by=e.edited_by)


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
        TimeEntry.user_id == user.id, TimeEntry.clock_out.is_not(None), TimeEntry.deleted_at.is_(None),
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
    return db.scalar(select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.clock_out.is_(None),
                                             TimeEntry.deleted_at.is_(None)))


@router.get("/status")
def status(user: User = Depends(require("time.clock")), db: Session = Depends(get_db)):
    e = _open_entry(db, user)
    return {"clocked_in": e is not None, "on_break": bool(e and e.break_start),
            "entry": _out(e, user.name) if e else None}


def _end_break(e: TimeEntry, now) -> None:
    if e.break_start:
        e.break_taken_min = (e.break_taken_min or 0) + max(0, round((now - e.break_start).total_seconds() / 60))
        e.break_start = None


@router.post("/break-start", response_model=TimeEntryOut)
def break_start(request: Request, user: User = Depends(require("time.clock")), db: Session = Depends(get_db)):
    e = _open_entry(db, user)
    if not e:
        raise HTTPException(409, "Sie sind nicht eingestempelt")
    if e.break_start:
        raise HTTPException(409, "Die Pause läuft bereits")
    e.break_start = utcnow()
    audit(db, user, "time.break_start", f"entry={e.id}", request)
    db.commit()
    changed(user.tenant_id, "time")
    return _out(e, user.name)


@router.post("/break-end", response_model=TimeEntryOut)
def break_end(request: Request, user: User = Depends(require("time.clock")), db: Session = Depends(get_db)):
    e = _open_entry(db, user)
    if not e or not e.break_start:
        raise HTTPException(409, "Es läuft keine Pause")
    _end_break(e, utcnow())
    audit(db, user, "time.break_end", f"entry={e.id} pause={e.break_taken_min}", request)
    db.commit()
    changed(user.tenant_id, "time")
    return _out(e, user.name)


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
    now = utcnow()
    _end_break(e, now)  # laufende Pause endet automatisch mit dem Ausstempeln
    e.clock_out = now
    audit(db, user, "time.clock_out", f"entry={e.id}", request)
    db.commit()
    changed(user.tenant_id, "time")
    return _out(e, user.name)


@router.get("/entries", response_model=list[TimeEntryOut])
def entries(start: UTCDateTime, end: UTCDateTime, user_id: Optional[int] = None, all: bool = False,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    can_approve = "time.approve" in permissions_for(db, user)
    q = select(TimeEntry, User.name).join(User, User.id == TimeEntry.user_id).where(
        TimeEntry.tenant_id == user.tenant_id, TimeEntry.deleted_at.is_(None),
        TimeEntry.clock_in >= start, TimeEntry.clock_in < end)
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
    if not e or e.tenant_id != user.tenant_id or e.deleted_at:
        raise HTTPException(404, "Eintrag nicht gefunden")
    before = f"in={e.clock_in} out={e.clock_out} approved={e.approved}"
    data = body.model_dump(exclude_unset=True)
    new_in = data["clock_in"] if data.get("clock_in") else e.clock_in
    new_out = data["clock_out"] if "clock_out" in data else e.clock_out
    if new_in != e.clock_in or new_out != e.clock_out:
        if e.orig_clock_in is None:  # erste Korrektur: Originalzeiten festhalten
            e.orig_clock_in, e.orig_clock_out = e.clock_in, e.clock_out
        e.edited_at, e.edited_by = utcnow(), user.name
    e.clock_in, e.clock_out = new_in, new_out
    if data.get("break_minutes") is not None and data["break_minutes"] != e.break_taken_min:
        e.break_taken_min, e.break_start = data["break_minutes"], None
        e.edited_at, e.edited_by = utcnow(), user.name
    if data.get("note") is not None:
        e.note = data["note"]
    if data.get("approved") is not None:
        e.approved = data["approved"]
    if e.clock_out and e.clock_out <= e.clock_in:
        db.rollback()
        raise HTTPException(422, "Das Ende muss nach dem Beginn liegen")
    if data.get("approved") is True:
        reason = deviation_reason(db, e)
        if reason and len((e.note or "").strip()) < 5:
            db.rollback()
            raise HTTPException(422, f"Abweichungskontrolle: {reason}. Bitte einen Kontrollvermerk (Notiz) eintragen, "
                                     "bevor der Eintrag freigegeben wird.")
    audit(db, user, "time.edit", f"entry={e.id} vorher: {before}", request)
    db.commit()
    changed(user.tenant_id, "time")
    return _out(e, db.get(User, e.user_id).name)


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, reason: str, request: Request,
                 user: User = Depends(require("time.approve")), db: Session = Depends(get_db)):
    """Zeiteintrag löschen (z. B. Fehlstempelung). Wird nur ausgeblendet und protokolliert."""
    e = db.get(TimeEntry, entry_id)
    if not e or e.tenant_id != user.tenant_id or e.deleted_at:
        raise HTTPException(404, "Eintrag nicht gefunden")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(422, "Bitte eine Begründung für das Löschen angeben (mind. 5 Zeichen).")
    e.deleted_at, e.delete_reason = utcnow(), reason[:500]
    audit(db, user, "time.delete", f"entry={e.id} user={e.user_id} in={e.clock_in} out={e.clock_out} grund={reason}"[:400], request)
    db.commit()
    changed(user.tenant_id, "time")
