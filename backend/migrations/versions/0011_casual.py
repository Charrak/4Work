"""v1.10: Flag is_casual (Aushilfe, kein Stundenkonto). Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    if "is_casual" not in have:
        op.add_column("users", sa.Column("is_casual", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("users", "is_casual")
