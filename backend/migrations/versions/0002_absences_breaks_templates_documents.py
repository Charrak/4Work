"""v1.1: Abwesenheitsarten, Pausen, Schichtvorlagen, Dokumente.

Idempotent: Auf einer neu angelegten Datenbank (Baseline kennt die Felder schon) passiert nichts.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _has_col(insp, table, col):
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not _has_col(insp, "leave_requests", "kind"):
        op.add_column("leave_requests", sa.Column("kind", sa.String(20), nullable=False, server_default="vacation"))
    if not _has_col(insp, "shifts", "break_minutes"):
        op.add_column("shifts", sa.Column("break_minutes", sa.Integer(), nullable=False, server_default="0"))
    # Neue Tabellen (shift_templates, documents) über die Modelle anlegen, falls sie fehlen
    from app import models  # noqa: F401
    from app.db import Base
    Base.metadata.create_all(bind=bind, tables=[
        Base.metadata.tables["shift_templates"], Base.metadata.tables["documents"]])
    # Neue Rechte für bestehende Installationen: Standardrechte für Dokumente ergänzen
    if insp.has_table("role_permissions"):
        rp = sa.table("role_permissions", sa.column("tenant_id"), sa.column("role"), sa.column("permission"))
        tenants = [r[0] for r in bind.execute(sa.text("SELECT id FROM tenants"))]
        for t in tenants:
            for role in ("mitarbeiter", "benutzer"):
                exists = bind.execute(sa.text(
                    "SELECT 1 FROM role_permissions WHERE tenant_id=:t AND role=:r AND permission='documents.view'"),
                    {"t": t, "r": role}).first()
                if not exists:
                    bind.execute(rp.insert().values(tenant_id=t, role=role, permission="documents.view"))


def downgrade():
    pass  # bewusst keine Rückwärts-Migration (Datenverlust); stattdessen Backup einspielen
