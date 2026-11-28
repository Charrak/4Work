"""v1.9: Pausen per Stempeluhr (laufende Pause, Summe genommener Pausen). Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

COLS = [("break_start", sa.DateTime()), ("break_taken_min", sa.Integer())]


def upgrade():
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("time_entries")}
    for name, typ in COLS:
        if name not in have:
            op.add_column("time_entries", sa.Column(name, typ, nullable=True))


def downgrade():
    for name, _ in COLS:
        op.drop_column("time_entries", name)
