import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm.exc import StaleDataError

from .config import settings
from .db import Base, SessionLocal, engine
from .deps import user_from_token
from .hub import hub
from .ratelimit import api_limiter
from .logging_setup import setup_logging
from . import models  # noqa: F401  (registriert alle Tabellen)
from .routers import (admin, auth, availability, documents, personnel, leave, messages, reports, shifts, swaps, tasks, templates, time,
                      users)

setup_logging()
log = logging.getLogger("dienstplan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    log.info("Dienstplan %s gestartet (%s)", settings.version, settings.env)
    yield


app = FastAPI(title="Dienstplan API", version=settings.version, lifespan=lifespan,
              docs_url="/api/docs" if settings.enable_api_docs else None,
              redoc_url="/api/redoc" if settings.enable_api_docs else None,
              openapi_url="/api/openapi.json" if settings.enable_api_docs else None)

if settings.allowed_origins:
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def global_rate_limit(request: Request, call_next):
    """Allgemeine Obergrenze je Client-IP (zusätzlich zu den strengeren Limits für Login, Upload usw.)."""
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        try:
            api_limiter(request)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail}, headers=e.headers or {})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.url.path.startswith("/api/") and not request.url.path.startswith(("/api/docs", "/api/redoc", "/api/openapi")):
        response.headers.setdefault("Cache-Control", "private, no-cache")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
    if not request.url.path.startswith("/api/docs") and not request.url.path.startswith("/api/redoc"):
        response.headers.setdefault("Content-Security-Policy",
                                    "default-src 'none'; frame-ancestors 'none'")
    if settings.cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(StaleDataError)
async def stale_handler(request: Request, exc: StaleDataError):
    return JSONResponse(status_code=409, content={"detail": {
        "message": "Der Datensatz wurde gleichzeitig geändert. Bitte neu laden.", "current_version": None}})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unbehandelter Fehler bei %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Interner Serverfehler"})


@app.get("/api/health", tags=["system"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error", "database": "down"})
    return {"status": "ok", "database": "up", "version": settings.version}


for r in (auth.router, users.router, users.roles_router, users.dept_router, shifts.router, swaps.router,
          leave.router, time.router, reports.router, messages.router, admin.router,
          templates.router, documents.router, availability.router, personnel.router,
          tasks.router, tasks.template_router):
    app.include_router(r)


@app.websocket("/api/ws")
async def ws_endpoint(ws: WebSocket):
    origin = ws.headers.get("origin")
    allowed = settings.allowed_origins or ((settings.app_url,) if settings.env == "production" else ())
    if allowed and origin and origin not in allowed:
        await ws.close(code=4403)
        return
    with SessionLocal() as db:
        user = user_from_token(db, ws.cookies.get("access_token"))
        ident = (user.tenant_id, user.id) if user else None
    if not ident:
        await ws.close(code=4401)
        return
    tenant_id, user_id = ident
    await hub.connect(ws, tenant_id, user_id)
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws, tenant_id)
