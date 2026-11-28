"""Ersteinrichtung per Kommandozeile (install.sh ruft setup-company auf)."""
from argparse import Namespace

from sqlalchemy import select

from app.cli import cmd_seed_demo, cmd_setup_company
from app.db import SessionLocal
from app.models import Department


def _names():
    with SessionLocal() as db:
        return [d.name for d in db.scalars(select(Department).order_by(Department.id))]


def _args(**kw):
    base = dict(company="Test GmbH", departments="Physiotherapie,Fitness", email="chef@test.de",
                name="Chef", password="Test-Passwort-123")
    base.update(kw)
    return Namespace(**base)


def test_setup_company_with_default_departments(client):
    assert cmd_setup_company(_args()) == 0
    assert sorted(_names()) == ["Fitness", "Physiotherapie"]
    assert cmd_setup_company(_args()) == 1          # zweiter Aufruf: bereits eingerichtet


def test_setup_company_with_other_departments(client):
    assert cmd_setup_company(_args(departments="Fitness,Reha,Theke")) == 0
    assert sorted(_names()) == ["Fitness", "Reha", "Theke"]


def test_setup_company_with_single_department(client):
    assert cmd_setup_company(_args(departments="Studio")) == 0
    assert _names() == ["Studio"]


def test_seed_demo_on_empty_database(client):
    assert cmd_seed_demo(Namespace()) == 0
    assert sorted(_names()) == ["Fitness", "Physiotherapie"]
