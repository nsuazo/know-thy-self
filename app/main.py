"""App factory, startup and the nightly export loop."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import jobs
from .config import settings
from .days import now_local
from .db import connect, init_db
from .export import export_all
from .guard import RequestGuard
from .routes import history, jobs_api, journal, profile, review

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("know-thy-self")


def _run_export() -> None:
    conn = connect()
    try:
        export_all(conn)
    finally:
        conn.close()


async def export_loop() -> None:
    while True:
        now = now_local()
        target = now.replace(hour=settings.export_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await asyncio.to_thread(_run_export)
        except Exception:
            log.exception("Nightly export failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    conn = connect()
    try:
        jobs.fail_stale_jobs(conn)
    finally:
        conn.close()
    task = asyncio.create_task(export_loop()) if 0 <= settings.export_hour <= 23 else None
    log.info("Know Thy Self started; data dir %s", settings.data_dir)
    yield
    if task:
        task.cancel()


app = FastAPI(title="Know Thy Self", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(RequestGuard)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(journal.router)
app.include_router(history.router)
app.include_router(jobs_api.router)
app.include_router(review.router)
app.include_router(profile.router)
