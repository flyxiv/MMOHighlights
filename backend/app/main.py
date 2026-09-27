import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.api import channels, labels, recordings, system
from app.config import Settings, get_settings
from app.platforms import Platforms
from app.services import Services
from app.storage import Storage, make_storage


def create_app(
    settings: Settings | None = None, *, storage: Storage | None = None, platforms: Platforms | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = Services.build(settings, db.sessionmaker(), storage or make_storage(settings), platforms)
        app.state.services = services
        if settings.run_workers:
            await services.start()
        try:
            yield
        finally:
            if settings.run_workers:
                await services.stop()
            else:
                await services.platforms.aclose()
            await db.dispose()

    app = FastAPI(title="MMOHighlights recorder", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (channels, recordings, labels, system):
        app.include_router(module.router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
