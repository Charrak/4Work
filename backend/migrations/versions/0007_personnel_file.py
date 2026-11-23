"""v1.6: Personalakte (Telefon, Funktion, Eintritt, Vertragsende, interne Notiz). Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

COLS = [("phone", sa.String(40)), ("job_title", sa.String(100)), ("hire_date", sa.Date()),
        ("contract_end", sa.Date()), ("hr_note", sa.Text())]


def upgrade():
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    for name, typ in COLS:
        if name not in have:
            op.add_column("users", sa.Column(name, typ, nullable=True))


def downgrade():
    for name, _ in COLS:
        op.drop_column("users", name)
