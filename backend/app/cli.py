"""Kommandozeile für Betrieb und Wartung:
  python -m app.cli create-admin --company "Muster GmbH" --email a@b.de --name Anna --password '...'
  python -m app.cli seed-demo
  python -m app.cli backup
"""
import argparse
import base64
import os
import sys
from datetime import datetime, timedelta

from sqlalchemy import select

from .db import Base, SessionLocal, engine
from . import models
from .models import Department, Shift, User
from .security import hash_password
from .services import backup as backup_service
from .services.common import seed_role_permissions
from .services.tenants import create_tenant_with_admin
from .utils import _check_password, utcnow

DEMO_PASSWORD = "Demo-Passwort-1234"


def cmd_create_admin(a) -> int:
    Base.metadata.create_all(engine) if a.create_tables else None
    with SessionLocal() as db:
        try:
            create_tenant_with_admin(db, a.company, a.email.lower(), a.name, a.password)
        except ValueError as e:
            print(f"Fehler: {e}")
            return 1
        db.commit()
    print("Administrator angelegt.")
    return 0


def cmd_setup_company(a) -> int:
    """Richtet die EINE Firma mit ihren Abteilungen und dem ersten Administrator ein."""
    password = a.password or os.environ.get("ADMIN_PASSWORD", "")
    try:
        _check_password(password)
    except ValueError as e:
        print(f"Fehler: {e}")
        return 1
    a.password = password
    Base.metadata.create_all(engine)
    names = [n.strip() for n in a.departments.split(",") if n.strip()]
    with SessionLocal() as db:
        if db.scalar(select(User.id)):
            print("Die Firma ist bereits eingerichtet.")
            return 1
        try:
            admin = create_tenant_with_admin(db, a.company, a.email.lower(), a.name, a.password)
        except ValueError as e:
            print(f"Fehler: {e}")
            return 1
        # Die Firma bringt Standard-Abteilungen mit: der Reihe nach umbenennen, fehlende ergänzen,
        # überzählige entfernen (keine doppelten Namen – sonst Fehler wegen eindeutiger Abteilungsnamen)
        existing = db.scalars(select(Department).where(Department.tenant_id == admin.tenant_id)
                              .order_by(Department.id)).all()
        names = list(dict.fromkeys(names)) or [existing[0].name]
        for d in existing:               # erst Platzhalter, damit Umbenennen keine Kollision auslöst
            d.name = f"__tmp_{d.id}"
        db.flush()
        for i, n in enumerate(names):
            if i < len(existing):
                existing[i].name = n
            else:
                db.add(Department(tenant_id=admin.tenant_id, name=n))
        for d in existing[len(names):]:
            if d.id != existing[0].id:
                db.delete(d)
        db.commit()
    print(f"Firma '{a.company}' mit Abteilungen {', '.join(names)} eingerichtet.")
    return 0


def cmd_seed_demo(a) -> int:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)):
            print("Es sind bereits Daten vorhanden. Demo-Daten werden nur in eine leere Datenbank eingespielt.")
            return 1
        admin = create_tenant_with_admin(db, "physio & fit VitalZentrum Eschweiler (Demo)", "admin@demo.local", "Dora Admin", DEMO_PASSWORD)
        t = admin.tenant_id
        depts = db.scalars(select(Department).where(Department.tenant_id == t).order_by(Department.id)).all()
        service = depts[0]
        service.name = "Physiotherapie"
        kitchen = next((d for d in depts if d.name == "Fitness"), None)
        if kitchen is None:
            kitchen = Department(tenant_id=t, name="Fitness")
            db.add(kitchen)
        db.flush()
        people = [("planer@demo.local", "Paul Planer", "mitarbeiter", [service, kitchen])]
        names = ["Anna Beck", "Ben Conrad", "Clara Dietz", "David Ebert", "Eva Fuchs", "Felix Graf"]
        for i, n in enumerate(names):
            people.append((f"{n.split()[0].lower()}@demo.local", n, "benutzer", [service] if i % 2 == 0 else [kitchen]))
        users = []
        for email, name, role, depts in people:
            u = User(tenant_id=t, email=email, name=name, role=role, password_hash=hash_password(DEMO_PASSWORD),
                     hourly_rate=14.5, vacation_days=28)
            u.departments = depts
            db.add(u)
            users.append(u)
        db.flush()
        monday = (utcnow() + timedelta(days=(7 - utcnow().weekday()))).replace(hour=0, minute=0, second=0, microsecond=0)
        staff = [u for u in users if u.role == "benutzer"]
        for day in range(14):
            d = monday + timedelta(days=day)
            for idx, u in enumerate(staff):
                if (day + idx) % 3 == 0:
                    continue
                start = d + timedelta(hours=8 if idx % 2 == 0 else 14)
                db.add(Shift(tenant_id=t, department_id=u.departments[0].id, user_id=u.id, start=start,
                             end=start + timedelta(hours=8), published=True,
                             note="Frühschicht" if idx % 2 == 0 else "Spätschicht"))
            db.add(Shift(tenant_id=t, department_id=service.id, user_id=None, published=True,
                         start=d + timedelta(hours=17), end=d + timedelta(hours=22), note="Vertretung",
                         claim_requires_approval=bool(day % 2)))
        db.commit()
    print(f"Demo-Betrieb angelegt. Logins: admin@demo.local, planer@demo.local, anna@demo.local (Passwort: {DEMO_PASSWORD})")
    return 0


def cmd_backup(a) -> int:
    path = backup_service.create_backup()
    print(path)
    return 0


def cmd_gen_key(a) -> int:
    from .services import crypto
    print(crypto.generate_key())
    return 0


def cmd_decrypt_backup(a) -> int:
    """Entschlüsselt eine .enc-Sicherung (Passphrase aus BACKUP_PASSPHRASE). Ohne Argumente: stdin -> stdout (für restore.sh)."""
    from .services import crypto
    src = open(a.source, "rb") if a.source and a.source != "-" else sys.stdin.buffer
    dst = open(a.target, "wb") if a.target and a.target != "-" else sys.stdout.buffer
    try:
        crypto.decrypt_stream(src, dst, os.environ.get("BACKUP_PASSPHRASE", ""))
        dst.flush()
    except crypto.CryptoError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_encrypt_documents(a) -> int:
    """Verschlüsselt bereits vorhandene (alte, unverschlüsselte) Dokumente. Mehrfaches Ausführen ist unschädlich."""
    from pathlib import Path
    from .config import settings
    from .services import crypto
    if not settings.documents_key:
        print("DOCUMENTS_KEY ist nicht gesetzt - nichts getan.")
        return 1
    n = 0
    for f in Path(settings.documents_dir).glob("*"):
        if f.is_file() and not f.name.endswith(".tmp"):
            blob = f.read_bytes()
            if not crypto.is_encrypted_doc(blob):
                tmp = f.with_name(f.name + ".tmp")
                tmp.write_bytes(crypto.encrypt_doc(blob))
                tmp.replace(f)
                n += 1
    print(f"{n} Dokument(e) verschlüsselt.")
    return 0


def cmd_reset_password(a) -> int:
    """Notfall: Passwort eines Benutzers (z. B. des Administrators) per Server-Zugang neu setzen."""
    password = a.password or os.environ.get("ADMIN_PASSWORD", "")
    try:
        _check_password(password)
    except ValueError as e:
        print(f"Fehler: {e}")
        return 1
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == a.email.lower(), User.deleted_at.is_(None)))
        if not u:
            print("Benutzer nicht gefunden.")
            return 1
        u.password_hash = hash_password(password)
        u.token_version += 1
        u.failed_logins = 0
        u.locked_until = None
        db.commit()
    print("Passwort gesetzt. Alle bisherigen Sitzungen wurden beendet.")
    return 0


def cmd_gen_vapid(a) -> int:
    """Erzeugt VAPID-Schlüssel für Web-Push (optional). Ausgabe als .env-Zeilen."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    priv = b64(key.private_numbers().private_value.to_bytes(32, "big"))
    pub = b64(key.public_key().public_bytes(serialization.Encoding.X962,
                                            serialization.PublicFormat.UncompressedPoint))
    print(f"VAPID_PRIVATE_KEY={priv}")
    print(f"VAPID_PUBLIC_KEY={pub}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-admin")
    c.add_argument("--company", required=True)
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--password", required=True)
    c.add_argument("--create-tables", action="store_true")
    c.set_defaults(fn=cmd_create_admin)
    sc = sub.add_parser("setup-company")
    sc.add_argument("--company", default="physio & fit VitalZentrum Eschweiler")
    sc.add_argument("--departments", default="Physiotherapie,Fitness",
                    help="Kommagetrennt, z. B. 'Physiotherapie,Fitness'")
    sc.add_argument("--email", required=True)
    sc.add_argument("--name", required=True)
    sc.add_argument("--password", default="", help="Alternativ per Umgebungsvariable ADMIN_PASSWORD")
    sc.set_defaults(fn=cmd_setup_company)
    sub.add_parser("seed-demo").set_defaults(fn=cmd_seed_demo)
    sub.add_parser("backup").set_defaults(fn=cmd_backup)
    sub.add_parser("gen-vapid").set_defaults(fn=cmd_gen_vapid)
    sub.add_parser("gen-key").set_defaults(fn=cmd_gen_key)
    sub.add_parser("encrypt-documents").set_defaults(fn=cmd_encrypt_documents)
    dec = sub.add_parser("decrypt-backup")
    dec.add_argument("source", nargs="?", default="-")
    dec.add_argument("target", nargs="?", default="-")
    dec.set_defaults(fn=cmd_decrypt_backup)
    rp = sub.add_parser("reset-password")
    rp.add_argument("--email", required=True)
    rp.add_argument("--password", default="", help="Alternativ per Umgebungsvariable ADMIN_PASSWORD")
    rp.set_defaults(fn=cmd_reset_password)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
