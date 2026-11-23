from sqlalchemy import select

from ..models import Department, Tenant, User
from ..security import hash_password
from .audit import audit
from .common import seed_role_permissions


DEFAULT_DEPARTMENTS = ("Physiotherapie", "Fitness")


def create_tenant_with_admin(db, company: str, email: str, name: str, password: str, request=None) -> User:
    if db.scalar(select(User.id).where(User.email == email)):
        raise ValueError("Diese E-Mail-Adresse ist bereits vergeben")
    t = Tenant(name=company)
    db.add(t)
    db.flush()
    seed_role_permissions(db, t.id)
    dept = Department(tenant_id=t.id, name=DEFAULT_DEPARTMENTS[0])
    db.add(dept)
    for extra in DEFAULT_DEPARTMENTS[1:]:
        db.add(Department(tenant_id=t.id, name=extra))
    admin = User(tenant_id=t.id, email=email, name=name, password_hash=hash_password(password),
                 role="admin", vacation_days=30)
    admin.departments = [dept]
    db.add(admin)
    db.flush()
    audit(db, admin, "tenant.create", f"Firma '{company}' angelegt", request)
    return admin
