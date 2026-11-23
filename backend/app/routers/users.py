import secrets
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require
from ..models import (Availability, WageHistory, Department, Document, LeaveRequest, Message, PushSubscription, RolePermission,
                      Shift, ShiftClaim, TimeEntry, User)
from ..permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
from ..schemas import (WageOut, DepartmentIn, DepartmentOut, RolePermissionsIn, SetPassword, UserCreate,
                       UserOut, UserUpdate)
from ..security import hash_password
from ..services.audit import audit
from ..services.limits import get_limit
from ..services.common import (changed, check_version, get_department_or_404, get_user_or_404,
                               permissions_for)
from ..utils import utcnow

router = APIRouter(prefix="/api/users", tags=["users"])
roles_router = APIRouter(prefix="/api/roles", tags=["roles"])
dept_router = APIRouter(prefix="/api/departments", tags=["departments"])


def _departments(db, tenant_id, ids):
    ids = sorted(set(ids))
    if not ids:
        return []
    depts = db.scalars(select(Department).where(Department.tenant_id == tenant_id,
                                                Department.id.in_(ids))).all()
    if len(depts) != len(ids):
        raise HTTPException(422, "Unbekannte Abteilung angegeben")
    return list(depts)


def _other_admins(db, tenant_id, exclude_id) -> int:
    return db.scalar(select(func.count(User.id)).where(
        User.tenant_id == tenant_id, User.role == "admin", User.is_active.is_(True),
        User.deleted_at.is_(None), User.id != exclude_id)) or 0


def _admin_only(actor: User, target_role: str) -> None:
    """Nur Administratoren dürfen Administratorkonten anlegen, ändern, sperren, löschen oder deren Passwort setzen
    (verhindert Rechteausweitung durch Nutzer mit bloß „users.manage“)."""
    if target_role == "admin" and actor.role != "admin":
        raise HTTPException(403, "Nur Administratoren dürfen Administratorkonten verwalten")


def _check_wage(db, user: User, rate, ignore: bool) -> None:
    """Stundenlohn unter dem gesetzlichen Mindestlohn: Hinweis, bewusst übergehbar (z. B. Azubi, Praktikum)."""
    if rate is None or rate <= 0:
        return
    minimum = get_limit(db, user.tenant_id, "minimum_wage")
    if rate < minimum and not ignore:
        raise HTTPException(422, detail={
            "message": f"Der Stundenlohn {rate:.2f} € liegt unter dem Mindestlohn ({minimum:.2f} €). "
                       "Ausnahmen (z. B. Auszubildende, Pflichtpraktikum) bitte bewusst bestätigen.",
            "warnings": ["minimum_wage"]})
    if rate < minimum:
        audit(db, user, "user.wage_below_minimum", f"rate={rate}")


@router.get("", response_model=list[UserOut])
def list_users(user: User = Depends(require("users.view")), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.tenant_id == user.tenant_id, User.deleted_at.is_(None))
                      .order_by(User.name)).all()
    if "users.manage" in permissions_for(db, user):
        return rows
    # Lohn- und Personendaten sehen nur Nutzer mit „users.manage“ (Datensparsamkeit)
    out = []
    for u in rows:
        o = UserOut.model_validate(u)
        o.hourly_rate = None
        o.weekly_hours = None
        o.is_minor = False
        o.is_minijob = False
        o.minijob_limit = None
        out.append(o)
    return out


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, user: User = Depends(require("users.manage")),
                db: Session = Depends(get_db)):
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(409, "Diese E-Mail-Adresse ist bereits vergeben")
    _admin_only(user, body.role)
    _check_wage(db, user, body.hourly_rate, body.ignore_warnings)
    new = User(tenant_id=user.tenant_id, email=body.email, name=body.name,
               password_hash=hash_password(body.password), role=body.role,
               hourly_rate=body.hourly_rate, vacation_days=body.vacation_days, work_days=body.work_days,
               weekly_hours=body.weekly_hours, is_minor=body.is_minor, is_minijob=body.is_minijob,
               minijob_limit=body.minijob_limit if body.is_minijob else None)
    new.departments = _departments(db, user.tenant_id, body.department_ids)
    db.add(new)
    db.flush()
    if new.hourly_rate:
        db.add(WageHistory(tenant_id=user.tenant_id, user_id=new.id, hourly_rate=new.hourly_rate,
                           valid_from=body.rate_valid_from or date.today(), created_by=user.id))
    audit(db, user, "user.create", f"user={new.id} role={new.role}", request)
    db.commit()
    changed(user.tenant_id, "users")
    return new


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, request: Request,
                user: User = Depends(require("users.manage")), db: Session = Depends(get_db)):
    target = get_user_or_404(db, user.tenant_id, user_id)
    _admin_only(user, target.role)
    _admin_only(user, body.role or target.role)
    check_version(target, body.version)
    data = body.model_dump(exclude_unset=True)
    data.pop("version")
    ignore = bool(data.pop("ignore_warnings", False))
    rate_from = data.pop("rate_valid_from", None)
    if data.get("hourly_rate") is not None:
        _check_wage(db, user, data["hourly_rate"], ignore)
    if "email" in data and data["email"] != target.email:
        if db.scalar(select(User.id).where(User.email == data["email"])):
            raise HTTPException(409, "Diese E-Mail-Adresse ist bereits vergeben")
    losing_admin = target.role == "admin" and (
        data.get("role", "admin") != "admin" or data.get("is_active", True) is False)
    if losing_admin:
        if target.id == user.id:
            raise HTTPException(400, "Sie können Ihre eigene Administratorrolle nicht entziehen oder sich selbst deaktivieren")
        if _other_admins(db, user.tenant_id, target.id) == 0:
            raise HTTPException(400, "Es muss mindestens ein aktiver Administrator vorhanden sein")
    if "department_ids" in data:
        target.departments = _departments(db, user.tenant_id, data.pop("department_ids") or [])
    if "hourly_rate" in data and data["hourly_rate"] != target.hourly_rate and data["hourly_rate"]:
        valid_from = rate_from or date.today()
        existing = db.scalar(select(WageHistory).where(WageHistory.user_id == target.id,
                                                       WageHistory.valid_from == valid_from))
        if existing:
            existing.hourly_rate = data["hourly_rate"]
        else:
            db.add(WageHistory(tenant_id=user.tenant_id, user_id=target.id, hourly_rate=data["hourly_rate"],
                               valid_from=valid_from, created_by=user.id))
        audit(db, user, "user.wage_change", f"user={target.id} ab={valid_from} satz={data['hourly_rate']}", request)
    for key, value in data.items():
        if key in ("email", "name", "role", "is_active", "vacation_days", "work_days", "is_minor", "is_minijob") and value is None:
            continue
        if key == "hourly_rate" and value and rate_from and rate_from > date.today():
            continue  # Satz gilt erst ab Zukunftsdatum; der Verlauf enthält ihn bereits
        setattr(target, key, value)
    if data.get("is_minijob") is False:
        target.minijob_limit = None
    if data.get("is_active") is False or "role" in data:
        target.token_version += 1  # Sitzungen mit alten Rechten beenden
    audit(db, user, "user.update", f"user={target.id} fields={','.join(sorted(data))}", request)
    db.commit()
    changed(user.tenant_id, "users")
    return target


@router.get("/{user_id}/wages", response_model=list[WageOut])
def wage_history(user_id: int, user: User = Depends(require("users.manage")), db: Session = Depends(get_db)):
    get_user_or_404(db, user.tenant_id, user_id)
    return db.scalars(select(WageHistory).where(WageHistory.user_id == user_id)
                      .order_by(WageHistory.valid_from.desc(), WageHistory.id.desc())).all()


@router.post("/{user_id}/lock", response_model=UserOut)
def lock_user(user_id: int, request: Request, user: User = Depends(require("users.manage")),
              db: Session = Depends(get_db)):
    target = get_user_or_404(db, user.tenant_id, user_id)
    _admin_only(user, target.role)
    if target.id == user.id:
        raise HTTPException(400, "Sie können sich nicht selbst sperren")
    if target.role == "admin" and _other_admins(db, user.tenant_id, target.id) == 0:
        raise HTTPException(400, "Der letzte Administrator kann nicht gesperrt werden")
    target.is_active = False
    target.token_version += 1
    audit(db, user, "user.lock", f"user={target.id}", request)
    db.commit()
    return target


@router.post("/{user_id}/unlock", response_model=UserOut)
def unlock_user(user_id: int, request: Request, user: User = Depends(require("users.manage")),
                db: Session = Depends(get_db)):
    target = get_user_or_404(db, user.tenant_id, user_id)
    _admin_only(user, target.role)
    target.is_active = True
    target.locked_until = None
    target.failed_logins = 0
    audit(db, user, "user.unlock", f"user={target.id}", request)
    db.commit()
    return target


@router.post("/{user_id}/set-password")
def set_password(user_id: int, body: SetPassword, request: Request,
                 user: User = Depends(require("users.manage")), db: Session = Depends(get_db)):
    target = get_user_or_404(db, user.tenant_id, user_id)
    _admin_only(user, target.role)
    target.password_hash = hash_password(body.password)
    target.token_version += 1
    audit(db, user, "user.set_password", f"user={target.id}", request)
    db.commit()
    return {"ok": True}


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request, delete_documents: bool = False,
                user: User = Depends(require("users.manage")), db: Session = Depends(get_db)):
    """DSGVO-Löschung: personenbezogene Daten werden anonymisiert. Schichten und Zeiteinträge
    bleiben ohne Personenbezug für Aufbewahrungspflichten erhalten."""
    target = get_user_or_404(db, user.tenant_id, user_id)
    _admin_only(user, target.role)
    if target.id == user.id:
        raise HTTPException(400, "Sie können sich nicht selbst löschen")
    if target.role == "admin" and _other_admins(db, user.tenant_id, target.id) == 0:
        raise HTTPException(400, "Der letzte Administrator kann nicht gelöscht werden")
    docs = db.scalars(select(Document).where(Document.user_id == target.id, Document.deleted_at.is_(None))).all()
    if docs and not delete_documents:
        raise HTTPException(409, f"Die Person hat {len(docs)} Dokument(e) (z. B. Vertrag). Bitte zuerst herunterladen "
                                 "und dann mit Löschung der Dokumente bestätigen (Aufbewahrungsfristen beachten).")
    now = utcnow()
    if docs:
        from .documents import delete_file
        for d in docs:
            d.deleted_at = now
            delete_file(d)
    target.email = f"geloescht-{target.id}@invalid.local"
    target.name = "Gelöschter Benutzer"
    target.password_hash = hash_password(secrets.token_urlsafe(24))
    target.is_active = False
    target.hourly_rate = None
    target.reset_token_hash = None
    target.reset_expires = None
    target.token_version += 1
    target.departments = []
    target.deleted_at = now
    db.execute(delete(Message).where(Message.user_id == target.id))
    db.execute(delete(Availability).where(Availability.user_id == target.id))
    target.is_minor = False
    target.phone = target.job_title = target.hr_note = None
    target.hire_date = target.contract_end = None
    db.execute(delete(PushSubscription).where(PushSubscription.user_id == target.id))
    db.execute(delete(ShiftClaim).where(ShiftClaim.user_id == target.id, ShiftClaim.status == "pending"))
    for s in db.scalars(select(Shift).where(Shift.user_id == target.id, Shift.start > now,
                                            Shift.deleted_at.is_(None))).all():
        s.user_id = None
    audit(db, user, "user.delete", f"user={target.id} anonymisiert", request)
    db.commit()
    changed(user.tenant_id, "users")
    changed(user.tenant_id, "shifts")


@router.get("/{user_id}/export")
def export_user(user_id: int, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """DSGVO Art. 15/20: Auskunft und Datenexport (eigene Daten oder mit users.manage)."""
    if user_id != user.id and "users.manage" not in permissions_for(db, user):
        raise HTTPException(403, "Keine Berechtigung")
    target = get_user_or_404(db, user.tenant_id, user_id)
    if user_id != user.id:
        _admin_only(user, target.role)
    iso = lambda d: d.isoformat() if d else None
    out = {
        "profil": {"id": target.id, "name": target.name, "email": target.email, "rolle": target.role,
                   "urlaubstage": target.vacation_days, "erstellt": iso(target.created_at),
                   "telefon": target.phone, "funktion": target.job_title, "eintritt": iso(target.hire_date),
                   "vertragsende": iso(target.contract_end), "interne_notiz": target.hr_note},
        "schichten": [{"start": iso(s.start), "ende": iso(s.end), "notiz": s.note} for s in db.scalars(
            select(Shift).where(Shift.user_id == target.id, Shift.deleted_at.is_(None)))],
        "zeiterfassung": [{"von": iso(t.clock_in), "bis": iso(t.clock_out), "freigegeben": t.approved,
                           "lat": t.lat, "lon": t.lon} for t in db.scalars(
            select(TimeEntry).where(TimeEntry.user_id == target.id))],
        "urlaub": [{"von": iso(l.start_date), "bis": iso(l.end_date), "status": l.status}
                   for l in db.scalars(select(LeaveRequest).where(LeaveRequest.user_id == target.id))],
        "nachrichten": [{"zeit": iso(m.created_at), "text": m.text} for m in db.scalars(
            select(Message).where(Message.user_id == target.id))],
    }
    audit(db, user, "user.export", f"user={target.id}", request)
    db.commit()
    return out


# ---------- Rollen ----------
@roles_router.get("")
def get_roles(user: User = Depends(require("roles.manage")), db: Session = Depends(get_db)):
    rows = db.scalars(select(RolePermission).where(RolePermission.tenant_id == user.tenant_id)).all()
    roles = {"admin": sorted(ALL_PERMISSIONS), "mitarbeiter": [], "benutzer": []}
    for r in rows:
        if r.role in roles and r.role != "admin":
            roles[r.role].append(r.permission)
    for k in ("mitarbeiter", "benutzer"):
        roles[k].sort()
    return {"permissions": ALL_PERMISSIONS, "roles": roles, "defaults": DEFAULT_ROLE_PERMISSIONS}


@roles_router.put("/{role}")
def set_role_permissions(role: str, body: RolePermissionsIn, request: Request,
                         user: User = Depends(require("roles.manage")), db: Session = Depends(get_db)):
    if role not in ("mitarbeiter", "benutzer"):
        raise HTTPException(400, "Nur die Rollen 'mitarbeiter' und 'benutzer' sind anpassbar")
    unknown = set(body.permissions) - set(ALL_PERMISSIONS)
    if unknown:
        raise HTTPException(422, f"Unbekannte Berechtigungen: {', '.join(sorted(unknown))}")
    if user.role != "admin":  # Rechteausweitung verhindern: nur Rechte weitergeben, die man selbst hat
        own = permissions_for(db, user)
        extra = set(body.permissions) - own
        if extra:
            raise HTTPException(403, f"Sie dürfen nur Rechte vergeben, die Sie selbst haben ({', '.join(sorted(extra))})")
    db.execute(delete(RolePermission).where(RolePermission.tenant_id == user.tenant_id,
                                            RolePermission.role == role))
    for p in sorted(set(body.permissions)):
        db.add(RolePermission(tenant_id=user.tenant_id, role=role, permission=p))
    audit(db, user, "role.update", f"role={role} permissions={','.join(sorted(set(body.permissions)))}", request)
    db.commit()
    return {"role": role, "permissions": sorted(set(body.permissions))}


# ---------- Abteilungen ----------
@dept_router.get("", response_model=list[DepartmentOut])
def list_departments(user: User = Depends(require("shifts.view")), db: Session = Depends(get_db)):
    return db.scalars(select(Department).where(Department.tenant_id == user.tenant_id)
                      .order_by(Department.name)).all()


@dept_router.post("", response_model=DepartmentOut, status_code=201)
def create_department(body: DepartmentIn, request: Request, user: User = Depends(require("shifts.manage")),
                      db: Session = Depends(get_db)):
    d = Department(tenant_id=user.tenant_id, name=body.name.strip())
    db.add(d)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Eine Abteilung mit diesem Namen existiert bereits")
    audit(db, user, "department.create", f"department={d.id}", request)
    db.commit()
    return d


@dept_router.patch("/{dept_id}", response_model=DepartmentOut)
def rename_department(dept_id: int, body: DepartmentIn, request: Request,
                      user: User = Depends(require("shifts.manage")), db: Session = Depends(get_db)):
    d = get_department_or_404(db, user.tenant_id, dept_id)
    d.name = body.name.strip()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Eine Abteilung mit diesem Namen existiert bereits")
    audit(db, user, "department.update", f"department={d.id}", request)
    db.commit()
    return d


@dept_router.delete("/{dept_id}", status_code=204)
def delete_department(dept_id: int, request: Request, user: User = Depends(require("shifts.manage")),
                      db: Session = Depends(get_db)):
    d = get_department_or_404(db, user.tenant_id, dept_id)
    if db.scalar(select(func.count(Shift.id)).where(Shift.department_id == d.id)):
        raise HTTPException(409, "Die Abteilung enthält noch Schichten")
    from ..models import user_departments
    db.execute(delete(user_departments).where(user_departments.c.department_id == d.id))
    db.delete(d)
    audit(db, user, "department.delete", f"department={dept_id}", request)
    db.commit()
