"""v1.8: Verfügbarkeit für einzelne Tage (on_date). Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("availabilities")}
    if "on_date" not in have:
        op.add_column("availabilities", sa.Column("on_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("availabilities", "on_date")
