import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Setting, Tenant, User
from ..ratelimit import limit_account, login_limiter, sensitive_limiter
from ..schemas import (CompanyOut, LoginIn, MeOut, PasswordChange, ResetConfirm, ResetRequest, TenantRegister,
                       UserOut)
from ..security import (DUMMY_HASH, create_access_token, hash_password, hash_token, verify_password)
from ..services.audit import audit
from ..services.common import permissions_for
from ..services.mailer import send_mail
from ..services.tenants import create_tenant_with_admin
from ..utils import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("dienstplan.auth")

MAX_FAILED = 5
LOCK_MINUTES = 15


def _set_cookies(response: Response, user: User) -> None:
    max_age = settings.access_token_minutes * 60
    response.set_cookie("access_token", create_access_token(user), httponly=True,
                        secure=settings.cookie_secure, samesite="lax", max_age=max_age, path="/")
    response.set_cookie("csrf_token", secrets.token_urlsafe(32), httponly=False,
                        secure=settings.cookie_secure, samesite="lax", max_age=max_age, path="/")


def _me(db: Session, user: User) -> MeOut:
    data = UserOut.model_validate(user).model_dump()
    return MeOut(**data, permissions=sorted(permissions_for(db, user)))


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)):
    """Zeigt dem Frontend, ob die Ersteinrichtung (erste Firma) noch offen ist."""
    count = db.scalar(select(func.count(Tenant.id))) or 0
    return {"setup_required": count == 0, "registration_open": count == 0 or settings.allow_registration}


@router.post("/register-tenant", response_model=MeOut, status_code=201,
             dependencies=[Depends(sensitive_limiter)])
def register_tenant(body: TenantRegister, request: Request, response: Response,
                    db: Session = Depends(get_db)):
    count = db.scalar(select(func.count(Tenant.id))) or 0
    if count > 0 and not settings.allow_registration:
        raise HTTPException(403, "Die Registrierung neuer Firmen ist deaktiviert")
    try:
        user = create_tenant_with_admin(db, body.company, body.email, body.name, body.password, request)
    except ValueError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    db.commit()
    _set_cookies(response, user)
    return _me(db, user)


@router.post("/login", response_model=MeOut, dependencies=[Depends(login_limiter)])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    limit_account(body.email)
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or user.deleted_at:
        verify_password(DUMMY_HASH, body.password)  # Timing angleichen
        raise HTTPException(401, "E-Mail oder Passwort falsch")
    if user.is_locked:
        raise HTTPException(423, "Konto vorübergehend gesperrt. Bitte später erneut versuchen.")
    if not verify_password(user.password_hash, body.password):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED:
            user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
            audit(db, user, "auth.locked", "Zu viele Fehlversuche", request)
        else:
            audit(db, user, "auth.failed", "", request)
        db.commit()
        raise HTTPException(401, "E-Mail oder Passwort falsch")
    if not user.is_active:
        raise HTTPException(403, "Dieses Konto ist deaktiviert")
    user.failed_logins = 0
    user.locked_until = None
    audit(db, user, "auth.login", "", request)
    db.commit()
    _set_cookies(response, user)
    return _me(db, user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("csrf_token", path="/")
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _me(db, user)


@router.post("/change-password", response_model=MeOut)
def change_password(body: PasswordChange, request: Request, response: Response,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Das aktuelle Passwort ist falsch")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # beendet alle anderen Sitzungen
    audit(db, user, "auth.password_change", "", request)
    db.commit()
    _set_cookies(response, user)
    return _me(db, user)


@router.post("/password-reset/request", status_code=202, dependencies=[Depends(sensitive_limiter)])
def password_reset_request(body: ResetRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    if user and user.is_active and not user.deleted_at:
        token = secrets.token_urlsafe(32)
        user.reset_token_hash = hash_token(token)
        user.reset_expires = utcnow() + timedelta(hours=1)
        audit(db, user, "auth.reset_requested", "", request)
        db.commit()
        link = f"{settings.app_url}/passwort-zuruecksetzen?token={token}"
        send_mail(user.email, "Passwort zurücksetzen",
                  f"Hallo {user.name},\n\nüber diesen Link können Sie ein neues Passwort setzen "
                  f"(1 Stunde gültig):\n{link}\n\nFalls Sie das nicht waren, ignorieren Sie diese Nachricht.")
    # Immer dieselbe Antwort, damit keine Konten erraten werden können
    return {"message": "Falls die Adresse bekannt ist, wurde eine E-Mail gesendet."}


@router.post("/password-reset/confirm", dependencies=[Depends(sensitive_limiter)])
def password_reset_confirm(body: ResetConfirm, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.reset_token_hash == hash_token(body.token)))
    if not user or not user.reset_expires or user.reset_expires < utcnow():
        raise HTTPException(400, "Der Link ist ungültig oder abgelaufen")
    user.password_hash = hash_password(body.new_password)
    user.reset_token_hash = None
    user.reset_expires = None
    user.token_version += 1
    user.failed_logins = 0
    user.locked_until = None
    audit(db, user, "auth.reset_done", "", request)
    db.commit()
    return {"ok": True}


@router.get("/company", response_model=CompanyOut)
def company(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Firmenname und Datenschutz-Ansprechpartner (für die Datenschutzseite in der App)."""
    def setting(key: str, default: str = "") -> str:
        row = db.get(Setting, (user.tenant_id, key))
        return row.value if row and row.value else default
    tenant = db.get(Tenant, user.tenant_id)
    return CompanyOut(company_name=setting("company_name", tenant.name if tenant else ""),
                      privacy_contact=setting("privacy_contact"))
