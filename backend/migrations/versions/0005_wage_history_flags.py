"""v1.4: Lohnverlauf, Jugendlich-/Minijob-Kennzeichen. Idempotent."""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("users")}
    for name in ("is_minor", "is_minijob"):
        if name not in cols:
            op.add_column("users", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))
    from app import models  # noqa: F401
    from app.db import Base
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["wage_history"]])
    # Bestehende Stundensätze als erster Verlaufseintrag (gültig seit Anlage)
    bind.execute(sa.text(
        "INSERT INTO wage_history (tenant_id, user_id, hourly_rate, valid_from, created_at) "
        "SELECT tenant_id, id, hourly_rate, DATE(created_at), created_at FROM users "
        "WHERE hourly_rate IS NOT NULL AND id NOT IN (SELECT user_id FROM wage_history)"))


def downgrade():
    op.drop_table("wage_history")
    op.drop_column("users", "is_minijob")
    op.drop_column("users", "is_minor")
