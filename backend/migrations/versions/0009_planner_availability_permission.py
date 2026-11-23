"""v1.8: Recht availability.manage für bestehende Planer-Rollen (alle Rollen "mitarbeiter", die shifts.manage haben). Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    rp = sa.table("role_permissions", sa.column("tenant_id", sa.Integer), sa.column("role", sa.String), sa.column("permission", sa.String))
    tenants = [r[0] for r in bind.execute(sa.select(rp.c.tenant_id).where(rp.c.role == "mitarbeiter", rp.c.permission == "shifts.manage")).fetchall()]
    for t in tenants:
        exists = bind.execute(sa.select(rp.c.tenant_id).where(rp.c.tenant_id == t, rp.c.role == "mitarbeiter",
                                                              rp.c.permission == "availability.manage")).first()
        if not exists:
            bind.execute(rp.insert().values(tenant_id=t, role="mitarbeiter", permission="availability.manage"))


def downgrade():
    pass
