"""v1.8: Zeiteinträge – Originalzeiten bei Korrektur, Bearbeiter, Löschen mit Begründung. Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

COLS = [("orig_clock_in", sa.DateTime()), ("orig_clock_out", sa.DateTime()), ("edited_at", sa.DateTime()),
        ("edited_by", sa.String(120)), ("deleted_at", sa.DateTime()), ("delete_reason", sa.String(500))]


def upgrade():
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("time_entries")}
    for name, typ in COLS:
        if name not in have:
            op.add_column("time_entries", sa.Column(name, typ, nullable=True))


def downgrade():
    for name, _ in COLS:
        op.drop_column("time_entries", name)
