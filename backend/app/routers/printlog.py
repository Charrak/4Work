"""Protokoll für Ausdrucke: Wer hat wann welche Ansicht mit personenbezogenen Daten gedruckt?

Der Browser meldet jeden Druckvorgang (auch Strg+P). So bleibt nachvollziehbar, wann Personaldaten
das System auf Papier verlassen haben (Rechenschaftspflicht, Art. 5 Abs. 2 DSGVO).
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..services.audit import audit

router = APIRouter(prefix="/api/print-log", tags=["datenschutz"])


class PrintIn(BaseModel):
    page: str = Field(max_length=100)
    detail: str = Field(default="", max_length=200)


@router.post("", status_code=204)
def log_print(body: PrintIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit(db, user, "print", f"{body.page} {body.detail}".strip()[:300], request)
    db.commit()
