import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import schemas, views
from app.db import get_session
from app.models import Channel, Recording, Tier
from app.services import Services, get_services
from app.util import ACTIVE_RECORDING_STATUSES

VIEWER_CANT_STOP = "This PC only views recordings. Stop it from the page on the recording PC."

router = APIRouter(prefix="/api/recordings", tags=["recordings"])

Session = Annotated[AsyncSession, Depends(get_session)]
Svc = Annotated[Services, Depends(get_services)]


@router.get("", response_model=schemas.RecordingPage)
async def list_recordings(
    session: Session,
    status_: Annotated[Literal["active", "completed"], Query(alias="status")] = "active",
    game_id: int | None = None,
    tier_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    statuses = ACTIVE_RECORDING_STATUSES if status_ == "active" else ("completed", "failed")
    where = [Recording.status.in_(statuses)]
    if game_id is not None:
        where.append(Recording.game_id == game_id)
    if tier_id is not None:
        where.append(Recording.tier_id == tier_id)
    total = (await session.execute(select(func.count()).select_from(Recording).where(*where))).scalar_one()
    recs = (
        (
            await session.execute(
                select(Recording)
                .where(*where)
                .options(
                    selectinload(Recording.channel),
                    selectinload(Recording.game),
                    selectinload(Recording.tier),
                )
                .order_by(Recording.started_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return schemas.RecordingPage(
        items=await views.recordings_out(session, list(recs)), total=total, page=page, page_size=page_size
    )


@router.get("/{recording_id}", response_model=schemas.RecordingDetailOut)
async def get_recording(recording_id: uuid.UUID, session: Session):
    out = await views.recording_detail(session, recording_id)
    if out is None:
        raise HTTPException(404, "No such recording.")
    return out


@router.post("/{recording_id}/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_recording(recording_id: uuid.UUID, session: Session, svc: Svc):
    rec = await session.get(Recording, recording_id)
    if rec is None:
        raise HTTPException(404, "No such recording.")
    if rec.status not in ("recording", "ending"):
        raise HTTPException(409, "This recording has already stopped.")
    if svc.is_viewer:
        raise HTTPException(409, VIEWER_CANT_STOP)
    await svc.supervisor.stop_manually(recording_id)
    return {"status": "finalizing"}


@router.patch("/{recording_id}", response_model=schemas.RecordingOut)
async def set_labels(recording_id: uuid.UUID, body: schemas.RecordingLabels, session: Session, svc: Svc):
    rec = await session.get(Recording, recording_id)
    if rec is None:
        raise HTTPException(404, "No such recording.")
    game_id, tier_id = body.game_id, body.tier_id
    if tier_id is not None:
        tier = await session.get(Tier, tier_id)
        if tier is None:
            raise HTTPException(422, "No such tier.")
        if game_id is None:
            game_id = tier.game_id
        elif tier.game_id != game_id:
            raise HTTPException(422, "That tier belongs to a different game.")
    rec.game_id, rec.tier_id = game_id, tier_id
    rec.labels_source = "manual" if game_id or tier_id else None
    # The channel remembers the latest labels and pre-fills its next recording with them.
    await session.execute(
        update(Channel)
        .where(Channel.id == rec.channel_id)
        .values(default_game_id=game_id, default_tier_id=tier_id)
    )
    await session.commit()
    out = await views.recording_by_id(session, recording_id)
    assert out is not None
    svc.bus.publish("recording.updated", out)
    ch = await views.channels_out(session, [out.channel.id])
    if ch:
        svc.bus.publish("channel.updated", ch[0])
    return out
