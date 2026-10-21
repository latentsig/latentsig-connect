import asyncio
import logging
from contextlib import asynccontextmanager
from collections import Counter
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.api.v1.routes.leads import router as leads_router
from app.api.v1.routes.ocr import router as ocr_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.exports import router as exports_router
from app.db.models import Event
from app.services.storage.business_cards import storage
from app.services.backup import create_backup

logger = logging.getLogger(__name__)


async def _sqlite_backup_loop():
    while True:
        try:
            backup_path = await asyncio.to_thread(create_backup)
            logger.info("Created verified SQLite database backup: %s", backup_path.name)
        except Exception:
            logger.exception("Scheduled SQLite database backup failed")
        await asyncio.sleep(24 * 60 * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.cleanup_expired_staging()
    if not app.dependency_overrides:
        with SessionLocal() as db:
            event = db.scalar(select(Event).where(Event.slug == settings.default_event_slug))
            if event is None:
                db.add(Event(name="Bengaluru Tech Summit 2026", slug=settings.default_event_slug, location="Bengaluru", is_active=True))
                db.commit()
    backup_task = None
    if settings.database_url.startswith("sqlite:") and not app.dependency_overrides:
        backup_task = asyncio.create_task(_sqlite_backup_loop())
    try:
        yield
    finally:
        if backup_task:
            backup_task.cancel()
            try:
                await backup_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="LatentSig Connect API", version="0.1.0", lifespan=lifespan)
_http_requests: Counter[tuple[str, str, int]] = Counter()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def record_http_metrics(request, call_next):
    started = perf_counter()
    response = await call_next(request)
    if request.url.path != "/metrics":
        route = request.scope.get("route")
        route_name = getattr(route, "path", "unmatched")
        _http_requests[(request.method, route_name, response.status_code)] += 1
    response.headers["Server-Timing"] = f"app;dur={(perf_counter() - started) * 1000:.1f}"
    return response
app.add_middleware(
    SessionMiddleware, secret_key=settings.app_secret,
    session_cookie=settings.session_cookie_name,
    max_age=settings.session_max_age_seconds,
    same_site="lax", https_only=settings.app_env.lower() == "production",
)
app.include_router(leads_router, prefix="/api/v1")
app.include_router(ocr_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(exports_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    lines = ["# HELP latentsig_http_requests_total Completed HTTP requests.", "# TYPE latentsig_http_requests_total counter"]
    for (method, route, status), count in sorted(_http_requests.items()):
        lines.append(f'latentsig_http_requests_total{{method="{method}",route="{route}",status="{status}"}} {count}')
    return "\n".join(lines) + "\n"
