"""v1.9: Aufgaben und Checklisten (Tabellen tasks, task_templates) und Standardrechte. Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

DEFAULTS = {
    "benutzer": ["tasks.do"],
    "mitarbeiter": ["tasks.do", "tasks.create", "tasks.manage", "tasks.stats"],
}


def upgrade():
    bind = op.get_bind()
    from app import models  # noqa: F401
    from app.db import Base
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["task_templates"], Base.metadata.tables["tasks"]])
    rp = sa.table("role_permissions", sa.column("tenant_id"), sa.column("role"), sa.column("permission"))
    for t in [r[0] for r in bind.execute(sa.text("SELECT id FROM tenants"))]:
        for role, perms in DEFAULTS.items():
            for p in perms:
                if not bind.execute(sa.text("SELECT 1 FROM role_permissions WHERE tenant_id=:t AND role=:r AND permission=:p"),
                                    {"t": t, "r": role, "p": p}).first():
                    bind.execute(rp.insert().values(tenant_id=t, role=role, permission=p))


def downgrade():
    pass
