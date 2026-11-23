"""Dokumentenverwaltung (Verträge, Atteste, Schulungen, Firmendokumente).

Sichtbarkeit:
  * documents.manage  -> alle Dokumente aller Personen (Standard: nur Administrator)
  * documents.view    -> eigene Dokumente + Firmendokumente (ohne Personenbezug)
Dateien liegen außerhalb des Webroots unter DOCUMENTS_DIR mit Zufallsnamen und werden nur über
diese geprüfte API ausgeliefert (immer als Download).
"""
import uuid
from urllib.parse import quote
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require
from ..models import Document, User
from ..ratelimit import upload_limiter
from ..services import crypto
from ..schemas import DocumentOut
from ..services.audit import audit
from ..services.common import get_user_or_404, permissions_for
from ..utils import utcnow

router = APIRouter(prefix="/api/documents", tags=["documents"])

CATEGORIES = {"vertrag", "attest", "schulung", "allgemein", "sonstiges"}
SELF_UPLOAD_CATEGORIES = {"attest", "sonstiges"}
ALLOWED = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
}
MAGIC = {".pdf": b"%PDF", ".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff",
         ".docx": b"PK", ".xlsx": b"PK"}


def storage_dir() -> Path:
    p = Path(settings.documents_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def delete_file(doc: Document) -> None:
    (Path(settings.documents_dir) / doc.stored_name).unlink(missing_ok=True)


def _names(db: Session, docs: list[Document]) -> dict[int, str]:
    ids = {d.user_id for d in docs if d.user_id}
    if not ids:
        return {}
    return {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids))).all()}


def _out(d: Document, names: dict[int, str]) -> DocumentOut:
    return DocumentOut(id=d.id, user_id=d.user_id, user_name=names.get(d.user_id) if d.user_id else None,
                       category=d.category, title=d.title, filename=d.filename, size=d.size,
                       created_at=d.created_at)


def _get(db: Session, user: User, doc_id: int, manage: bool) -> Document:
    d = db.get(Document, doc_id)
    visible = d and (manage or d.user_id == user.id or d.user_id is None)
    if not d or d.tenant_id != user.tenant_id or d.deleted_at or not visible:
        raise HTTPException(404, "Dokument nicht gefunden")
    return d


@router.get("", response_model=list[DocumentOut])
def list_documents(user_id: Optional[int] = None, user: User = Depends(require("documents.view")),
                   db: Session = Depends(get_db)):
    manage = "documents.manage" in permissions_for(db, user)
    q = select(Document).where(Document.tenant_id == user.tenant_id, Document.deleted_at.is_(None))
    if manage:
        if user_id:
            q = q.where(Document.user_id == user_id)
    else:
        q = q.where(or_(Document.user_id == user.id, Document.user_id.is_(None)))
    docs = list(db.scalars(q.order_by(Document.created_at.desc()).limit(500)).all())
    names = _names(db, docs)
    return [_out(d, names) for d in docs]


@router.post("", response_model=DocumentOut, status_code=201, dependencies=[Depends(upload_limiter)])
async def upload_document(request: Request, filename: str = Query(..., min_length=1, max_length=255),
                          title: str = Query("", max_length=200), category: str = Query("sonstiges"),
                          user_id: Optional[int] = Query(None),
                          user: User = Depends(require("documents.view")), db: Session = Depends(get_db)):
    """Datei als rohen Request-Body senden (kein Multipart nötig), Metadaten als Query-Parameter."""
    manage = "documents.manage" in permissions_for(db, user)
    if category not in CATEGORIES:
        raise HTTPException(422, "Unbekannte Kategorie")
    if not manage:
        if category not in SELF_UPLOAD_CATEGORIES:
            raise HTTPException(403, "Keine Berechtigung für diese Kategorie")
        user_id = user.id
    elif user_id:
        get_user_or_404(db, user.tenant_id, user_id)
    if category == "attest" and not user_id:
        raise HTTPException(422, "Ein Attest muss einer Person zugeordnet sein")

    name = Path(filename.replace("\\", "/")).name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(422, "Dateityp nicht erlaubt (erlaubt: PDF, PNG, JPG, DOCX, XLSX, TXT)")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > max_bytes:
        raise HTTPException(413, f"Datei zu groß (maximal {settings.max_upload_mb} MB)")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(413, f"Datei zu groß (maximal {settings.max_upload_mb} MB)")
    if not data:
        raise HTTPException(422, "Die Datei ist leer")
    magic = MAGIC.get(ext)
    if magic and bytes(data[:len(magic)]) != magic:
        raise HTTPException(422, "Der Dateiinhalt passt nicht zur Endung")

    stored = uuid.uuid4().hex
    await run_in_threadpool((storage_dir() / stored).write_bytes, crypto.encrypt_doc(bytes(data)))
    doc = Document(tenant_id=user.tenant_id, user_id=user_id, category=category,
                   title=(title.strip() or name)[:200], filename=name, content_type=ALLOWED[ext],
                   size=len(data), stored_name=stored, uploaded_by=user.id)
    db.add(doc)
    db.flush()
    audit(db, user, "document.upload", f"document={doc.id} kategorie={category} person={user_id}", request)
    db.commit()
    return _out(doc, _names(db, [doc]))


@router.get("/{doc_id}/download")
def download_document(doc_id: int, request: Request, user: User = Depends(require("documents.view")),
                      db: Session = Depends(get_db)):
    manage = "documents.manage" in permissions_for(db, user)
    d = _get(db, user, doc_id, manage)
    path = Path(settings.documents_dir) / d.stored_name
    if not path.is_file():
        raise HTTPException(404, "Die Datei fehlt auf dem Server")
    audit(db, user, "document.download", f"document={d.id}", request)
    db.commit()
    try:
        content = crypto.decrypt_doc(path.read_bytes())
    except crypto.CryptoError as e:
        raise HTTPException(500, str(e))
    ascii_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in d.filename)[:100] or "dokument"
    return Response(content, media_type=d.content_type, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(d.filename)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, request: Request, user: User = Depends(require("documents.manage")),
                    db: Session = Depends(get_db)):
    d = _get(db, user, doc_id, True)
    d.deleted_at = utcnow()
    delete_file(d)
    audit(db, user, "document.delete", f"document={d.id}", request)
    db.commit()
