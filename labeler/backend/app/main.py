import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import api
from app.config import Settings, get_settings
from app.index import Index
from app.labeler import Conflict, Invalid, Labeler, NotFound
from app.store import BlobStore, make_store

log = logging.getLogger(__name__)


def _sync_loop(lb: Labeler, stop: threading.Event, interval: float) -> None:
    backoff = interval
    while not stop.is_set():
        try:
            pushed = lb.push_pending()
        except Exception:
            log.exception("Sync loop error")
            pushed = 0
        if lb.last_sync_error:
            backoff = min(backoff * 2, 60)  # bucket unreachable: retry less often
        else:
            backoff = interval
        if not pushed or lb.last_sync_error:
            stop.wait(backoff)


def create_app(settings: Settings | None = None, *, store: BlobStore | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        index = Index(settings.cache_dir / "index.sqlite3")
        lb = Labeler(settings, store or make_store(settings.storage), index)
        app.state.labeler = lb
        stop = threading.Event()
        worker = None
        if settings.run_workers:
            worker = threading.Thread(
                target=_sync_loop, args=(lb, stop, settings.sync_interval_s), name="sync", daemon=True
            )
            worker.start()
        try:
            yield
        finally:
            stop.set()
            if worker:
                worker.join(timeout=5)
            lb.push_pending()  # last chance to get saved labels into the bucket
            lb.close()
            index.close()

    app = FastAPI(title="MMOHighlights labeler", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
    )

    def handler(status: int):
        def handle(_request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=status)

        return handle

    app.add_exception_handler(NotFound, handler(404))
    app.add_exception_handler(Conflict, handler(409))
    app.add_exception_handler(Invalid, handler(422))
    app.include_router(api.router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
