"""v1.2: Arbeitstage je Person (Teilzeit) und Verfügbarkeiten. Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not any(c["name"] == "work_days" for c in insp.get_columns("users")):
        op.add_column("users", sa.Column("work_days", sa.String(7), nullable=False, server_default="12345"))
    from app import models  # noqa: F401
    from app.db import Base
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["availabilities"]])


def downgrade():
    op.drop_table("availabilities")
    op.drop_column("users", "work_days")
