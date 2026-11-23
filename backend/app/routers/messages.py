from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Message, PushSubscription, User
from ..schemas import MessageIn, MessageOut, PushSubscribeIn
from ..config import settings
from ..services.common import changed
from ..hub import hub

router = APIRouter(prefix="/api", tags=["messages"])


@router.get("/messages", response_model=list[MessageOut])
def list_messages(after_id: int = 0, limit: int = 100, user: User = Depends(require("chat.use")),
                  db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    rows = db.execute(select(Message, User.name).join(User, User.id == Message.user_id).where(
        Message.tenant_id == user.tenant_id, Message.id > after_id)
        .order_by(Message.id.desc()).limit(limit)).all()
    return [MessageOut(id=m.id, user_id=m.user_id, user_name=n, text=m.text, created_at=m.created_at)
            for m, n in reversed(rows)]


@router.post("/messages", response_model=MessageOut, status_code=201)
def post_message(body: MessageIn, user: User = Depends(require("chat.use")), db: Session = Depends(get_db)):
    m = Message(tenant_id=user.tenant_id, user_id=user.id, text=body.text.strip())
    db.add(m)
    db.commit()
    hub.notify(user.tenant_id, "chat.message", {"id": m.id})
    return MessageOut(id=m.id, user_id=user.id, user_name=user.name, text=m.text, created_at=m.created_at)


@router.get("/push/public-key")
def push_public_key(user: User = Depends(require("shifts.view"))):
    return {"public_key": settings.vapid_public_key or None}


@router.post("/push/subscribe", status_code=201)
def push_subscribe(body: PushSubscribeIn, user: User = Depends(require("shifts.view")),
                   db: Session = Depends(get_db)):
    existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if existing:
        existing.user_id, existing.tenant_id = user.id, user.tenant_id
        existing.p256dh, existing.auth = body.p256dh, body.auth
    else:
        db.add(PushSubscription(tenant_id=user.tenant_id, user_id=user.id, endpoint=body.endpoint,
                                p256dh=body.p256dh, auth=body.auth))
    db.commit()
    return {"ok": True}
