import hmac
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import decode_access_token
from .services.common import permissions_for

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def user_from_token(db: Session, token: Optional[str]) -> Optional[User]:
    payload = decode_access_token(token) if token else None
    if not payload:
        return None
    try:
        user = db.get(User, int(payload["sub"]))
    except (KeyError, ValueError):
        return None
    if (not user or user.deleted_at or not user.is_active or user.is_locked
            or user.token_version != payload.get("tv")):
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    cookie_token = request.cookies.get("access_token")
    auth = request.headers.get("authorization", "")
    bearer = auth[7:] if auth.lower().startswith("bearer ") else None
    user = user_from_token(db, cookie_token or bearer)
    if not user:
        raise HTTPException(401, "Nicht angemeldet")
    # CSRF-Schutz (Double-Submit): nur nötig, wenn die Anmeldung über Cookie erfolgt
    if cookie_token and not bearer and request.method not in SAFE_METHODS:
        header = request.headers.get("x-csrf-token")
        if not header or not hmac.compare_digest(header, request.cookies.get("csrf_token") or ""):
            raise HTTPException(403, "CSRF-Prüfung fehlgeschlagen")
    return user


def require(permission: str):
    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if permission not in permissions_for(db, user):
            raise HTTPException(403, "Keine Berechtigung")
        return user
    return dependency
