"""v1.5: individuelle Minijob-Verdienstgrenze je Person (users.minijob_limit). Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if not any(c["name"] == "minijob_limit" for c in insp.get_columns("users")):
        op.add_column("users", sa.Column("minijob_limit", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("users", "minijob_limit")
