import shutil
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import engine, get_db
from ..deps import require
from ..models import AuditLog, LeaveRequest, Setting, Shift, SwapRequest, TimeEntry, User
from ..schemas import SettingsIn
from ..services import backup as backup_service
from ..services.audit import audit
from ..utils import utcnow

router = APIRouter(prefix="/api/admin", tags=["admin"])
STARTED = time.time()
ALLOWED_SETTINGS = {"company_name": 200, "timezone": 64, "default_vacation_days": 3, "privacy_contact": 300,
                    "minimum_wage": 8, "max_daily_hours": 5, "max_weekly_hours": 5,
                    "surcharge_night_pct": 6, "surcharge_sunday_pct": 6, "surcharge_holiday_pct": 6,
                    "minijob_limit": 8, "block_clock_over_limit": 1, "period_start_day": 2}


@router.get("/audit")
def audit_log(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              action: Optional[str] = None, user_id: Optional[int] = None,
              user: User = Depends(require("admin.audit")), db: Session = Depends(get_db)):
    q = select(AuditLog).where(AuditLog.tenant_id == user.tenant_id)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    rows = db.scalars(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return [{"id": r.id, "user_id": r.user_id, "action": r.action, "detail": r.detail, "ip": r.ip,
             "created_at": r.created_at.isoformat() + "Z"} for r in rows]


@router.get("/settings")
def get_settings(user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Setting).where(Setting.tenant_id == user.tenant_id)).all()
    return {r.key: r.value for r in rows}


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, user: User = Depends(require("settings.manage")),
                 db: Session = Depends(get_db)):
    for key, value in body.values.items():
        if key not in ALLOWED_SETTINGS:
            raise HTTPException(422, f"Unbekannte Einstellung: {key}")
        if len(value) > ALLOWED_SETTINGS[key]:
            raise HTTPException(422, f"Wert für {key} ist zu lang")
        if key == "default_vacation_days" and not (value.isdigit() and int(value) <= 365):
            raise HTTPException(422, "default_vacation_days muss eine Zahl bis 365 sein")
        if key == "period_start_day":
            if not (value.isdigit() and 1 <= int(value) <= 28):
                raise HTTPException(422, "period_start_day muss eine Zahl von 1 bis 28 sein")
            value = str(int(value))
        elif key == "block_clock_over_limit":
            value = "1" if value.strip().lower() in ("1", "true", "ja") else "0"
        elif key in ("minimum_wage", "max_daily_hours", "max_weekly_hours", "surcharge_night_pct",
                     "surcharge_sunday_pct", "surcharge_holiday_pct", "minijob_limit"):
            try:
                num = float(value.replace(",", "."))
            except ValueError:
                raise HTTPException(422, f"{key} muss eine Zahl sein")
            limits = {"minimum_wage": (0, 100), "max_daily_hours": (0, 24), "max_weekly_hours": (0, 168),
                      "surcharge_night_pct": (-1, 500), "surcharge_sunday_pct": (-1, 500),
                      "surcharge_holiday_pct": (-1, 500), "minijob_limit": (0, 5000)}[key]
            if not (limits[0] < num <= limits[1]):  # untere Grenze exklusiv
                raise HTTPException(422, f"{key} muss zwischen {limits[0]} und {limits[1]} liegen")
            value = str(num)
        row = db.get(Setting, (user.tenant_id, key))
        if row:
            row.value = value
        else:
            db.add(Setting(tenant_id=user.tenant_id, key=key, value=value))
    audit(db, user, "settings.update", ",".join(sorted(body.values)), request)
    db.commit()
    return {"ok": True}


@router.get("/system")
def system_info(user: User = Depends(require("admin.audit")), db: Session = Depends(get_db)):
    now = utcnow()
    t = user.tenant_id
    count = lambda q: db.scalar(q) or 0
    disk = shutil.disk_usage(Path(settings.backup_dir).parent if Path(settings.backup_dir).parent.exists() else ".")
    return {
        "version": settings.version,
        "environment": settings.env,
        "database": engine.url.get_backend_name(),
        "uptime_seconds": int(time.time() - STARTED),
        "disk_free_gb": round(disk.free / 1e9, 1),
        "backups": len(backup_service.list_backups()),
        "stats": {
            "users_active": count(select(func.count(User.id)).where(
                User.tenant_id == t, User.is_active.is_(True), User.deleted_at.is_(None))),
            "shifts_next_7_days": count(select(func.count(Shift.id)).where(
                Shift.tenant_id == t, Shift.deleted_at.is_(None), Shift.start >= now,
                Shift.start < now + timedelta(days=7))),
            "open_shifts": count(select(func.count(Shift.id)).where(
                Shift.tenant_id == t, Shift.deleted_at.is_(None), Shift.user_id.is_(None),
                Shift.start >= now)),
            "leave_pending": count(select(func.count(LeaveRequest.id)).where(
                LeaveRequest.tenant_id == t, LeaveRequest.status == "pending")),
            "swaps_waiting_approval": count(select(func.count(SwapRequest.id)).where(
                SwapRequest.tenant_id == t, SwapRequest.status == "accepted")),
            "clocked_in_now": count(select(func.count(TimeEntry.id)).where(
                TimeEntry.tenant_id == t, TimeEntry.clock_out.is_(None))),
        },
    }


@router.get("/logs")
def server_logs(lines: int = Query(200, ge=1, le=2000), user: User = Depends(require("admin.audit"))):
    """Letzte Zeilen des Anwendungsprotokolls (Fehlerprotokoll)."""
    path = Path(settings.log_dir) / "app.log"
    if not path.is_file():
        return {"lines": []}
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 512 * 1024))
        tail = f.read().decode("utf-8", errors="replace").splitlines()
    return {"lines": tail[-lines:]}


@router.get("/backups")
def list_backups(user: User = Depends(require("admin.backup"))):
    return [{**b, "created_at": b["created_at"].isoformat() + "Z"} for b in backup_service.list_backups()]


@router.post("/backups", status_code=201)
def create_backup(request: Request, user: User = Depends(require("admin.backup")),
                  db: Session = Depends(get_db)):
    try:
        path = backup_service.create_backup()
    except Exception as e:
        raise HTTPException(500, f"Backup fehlgeschlagen: {type(e).__name__}")
    audit(db, user, "backup.create", path.name, request)
    db.commit()
    return {"name": path.name, "size_bytes": path.stat().st_size}


@router.get("/backups/{name}")
def download_backup(name: str, request: Request, user: User = Depends(require("admin.backup")),
                    db: Session = Depends(get_db)):
    path = backup_service.backup_path(name)
    if not path:
        raise HTTPException(404, "Backup nicht gefunden")
    audit(db, user, "backup.download", name, request)
    db.commit()
    return FileResponse(path, filename=name, media_type="application/octet-stream")
