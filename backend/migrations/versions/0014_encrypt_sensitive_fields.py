"""v1.11: Sensible Textfelder verschlüsselt speichern (AES-256-GCM mit DOCUMENTS_KEY).

1. Spalten auf TEXT umstellen (der verschlüsselte Wert ist länger als der Klartext).
2. Vorhandene Klartexte verschlüsseln. Bereits verschlüsselte Werte ("enc1:…") bleiben unverändert,
   die Migration kann also gefahrlos mehrfach laufen. Ohne DOCUMENTS_KEY (nur Entwicklung) wird nichts verschlüsselt.
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

FIELDS = [("users", "phone"), ("users", "hr_note"), ("leave_requests", "note"),
          ("leave_requests", "decision_comment"), ("time_entries", "note"),
          ("time_entries", "delete_reason"), ("messages", "text")]


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, col in FIELDS:
        cols = {c["name"]: c for c in insp.get_columns(table)}
        if col in cols and not isinstance(cols[col]["type"], sa.Text):
            with op.batch_alter_table(table) as b:
                b.alter_column(col, type_=sa.Text(), existing_nullable=cols[col]["nullable"])

    from app.services.crypto import _doc_key, encrypt_field, is_encrypted_field
    if _doc_key() is None:
        return
    for table, col in FIELDS:
        rows = bind.execute(sa.text(f'SELECT id, "{col}" FROM {table} WHERE "{col}" IS NOT NULL AND "{col}" <> \'\'')).all()
        for rid, val in rows:
            if not is_encrypted_field(val):
                bind.execute(sa.text(f'UPDATE {table} SET "{col}" = :v WHERE id = :i'), {"v": encrypt_field(val), "i": rid})


def downgrade():
    # Entschlüsseln wäre nur mit Schlüssel möglich; Spaltentyp TEXT bleibt bestehen.
    pass
