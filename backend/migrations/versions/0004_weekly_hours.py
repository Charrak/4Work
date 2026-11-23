"""v1.3: Vertragsstunden pro Woche (users.weekly_hours). Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if not any(c["name"] == "weekly_hours" for c in insp.get_columns("users")):
        op.add_column("users", sa.Column("weekly_hours", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("users", "weekly_hours")
