import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app import schemas
from app.events import sse_format
from app.services import Services, get_services

router = APIRouter(prefix="/api", tags=["system"])

Svc = Annotated[Services, Depends(get_services)]


@router.get("/health", response_model=schemas.HealthOut)
async def health(svc: Svc):
    return await svc.health()


@router.get("/events")
async def events(request: Request, svc: Svc):
    async def stream():
        async with svc.bus.subscribe() as queue:
            yield sse_format("health", (await svc.health()).model_dump_json())
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield sse_format(event, data)
                except TimeoutError:
                    yield ": keep-alive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
