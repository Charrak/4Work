"""Datenschutz: verschlüsselte Datenbankfelder, Lohndaten nur mit eigenem Recht, Druckprotokoll."""
from sqlalchemy import text

from app.db import SessionLocal


def _raw(sql, **kw):
    with SessionLocal() as db:
        return db.execute(text(sql), kw).scalar()


def test_sensitive_fields_are_encrypted_at_rest(world):
    anna, admin = world["new_client"]("anna@test.de"), world["admin"]
    assert anna.post("/api/messages", json={"text": "Bin heute krank"}).status_code == 201
    r = anna.post("/api/leave", json={"start_date": "2030-03-04", "end_date": "2030-03-04", "kind": "sick", "note": "Arzttermin"})
    assert r.status_code == 201, r.text
    raw_msg = _raw("SELECT text FROM messages ORDER BY id DESC LIMIT 1")
    raw_note = _raw("SELECT note FROM leave_requests WHERE id = :i", i=r.json()["id"])
    assert raw_msg.startswith("enc1:") and "krank" not in raw_msg
    assert raw_note.startswith("enc1:") and "Arzt" not in raw_note
    # Anwendung liefert weiterhin Klartext
    assert admin.get("/api/messages").json()[-1]["text"] == "Bin heute krank"
    mine = anna.get("/api/leave").json()
    assert any(x["note"] == "Arzttermin" for x in mine)


def test_legacy_plaintext_fields_are_still_readable(world):
    anna = world["new_client"]("anna@test.de")
    anna.post("/api/messages", json={"text": "neu"})
    with SessionLocal() as db:
        db.execute(text("UPDATE messages SET text = 'alter Klartext'"))
        db.commit()
    assert anna.get("/api/messages").json()[-1]["text"] == "alter Klartext"


def test_field_crypto_roundtrip_and_wrong_key(monkeypatch):
    import pytest
    from app.services import crypto
    enc = crypto.encrypt_field("Telefon 0170 123")
    assert enc.startswith("enc1:") and crypto.decrypt_field(enc) == "Telefon 0170 123"
    assert crypto.encrypt_field("") == "" and crypto.encrypt_field(None) is None
    import os
    monkeypatch.setattr(crypto, "_doc_key", lambda: os.urandom(32))   # anderer Schlüssel
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_field(enc)


def test_wages_only_with_permission(world):
    admin, planer = world["admin"], world["new_client"]("planer@test.de")
    q = "start=2030-01-01T00:00:00Z&end=2030-02-01T00:00:00Z"
    rep = planer.get(f"/api/reports/summary?{q}").json()
    assert rep["wages_visible"] is False
    assert all(r["labor_cost"] is None and r["gross_cost"] is None for r in rep["rows"])
    csv = planer.get(f"/api/reports/payroll.csv?{q}").text
    assert "Brutto" not in csv and "Grundlohn" not in csv
    full = admin.get(f"/api/reports/summary?{q}").json()
    assert full["wages_visible"] is True and all(r["labor_cost"] is not None for r in full["rows"])
    assert "Brutto (EUR)" in admin.get(f"/api/reports/payroll.csv?{q}").text
    assert any(a["action"] == "report.export" for a in admin.get("/api/admin/audit").json())


def test_print_is_logged(world):
    anna, admin = world["new_client"]("anna@test.de"), world["admin"]
    assert anna.post("/api/print-log", json={"page": "/zeit", "detail": "Stundenzettel"}).status_code == 204
    entries = admin.get("/api/admin/audit?action=print").json()
    assert any("/zeit" in a["detail"] for a in entries)
