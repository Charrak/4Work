from typing import Optional

from fastapi import Request

from ..models import AuditLog
from ..ratelimit import client_ip


def audit(db, user, action: str, detail: str = "", request: Optional[Request] = None,
          tenant_id: Optional[int] = None, user_id: Optional[int] = None) -> None:
    """Fügt einen Audit-Eintrag zur laufenden Transaktion hinzu (Commit macht der Aufrufer)."""
    db.add(AuditLog(
        tenant_id=tenant_id if tenant_id is not None else (user.tenant_id if user else None),
        user_id=user_id if user_id is not None else (user.id if user else None),
        action=action,
        detail=detail[:2000],
        ip=client_ip(request) if request is not None else None,
    ))
