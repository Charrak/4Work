"""v1.12: Monatslohn statt nur Stundensatz (Benutzer und Lohnverlauf). Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    for table in ("users", "wage_history"):
        if "monthly_salary" not in {c["name"] for c in insp.get_columns(table)}:
            op.add_column(table, sa.Column("monthly_salary", sa.Float(), nullable=True))


def downgrade():
    for table in ("users", "wage_history"):
        op.drop_column(table, "monthly_salary")
