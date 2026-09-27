import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas, views
from app.db import get_session
from app.models import Channel, Recording
from app.platforms.base import ChannelNotFound, NotConfigured, PlatformError, UnsupportedUrl
from app.platforms.urls import parse_channel_url
from app.services import Services, get_services
from app.util import utcnow

router = APIRouter(prefix="/api/channels", tags=["channels"])

Session = Annotated[AsyncSession, Depends(get_session)]
Svc = Annotated[Services, Depends(get_services)]


@router.get("", response_model=list[schemas.ChannelOut])
async def list_channels(session: Session):
    return await views.channels_out(session)


@router.post("", response_model=schemas.ChannelOut, status_code=status.HTTP_201_CREATED)
async def add_channel(body: schemas.ChannelCreate, session: Session, svc: Svc):
    try:
        parsed = parse_channel_url(body.url)
    except UnsupportedUrl as e:
        raise HTTPException(422, str(e)) from e

    tracked = (
        await session.execute(select(func.count()).select_from(Channel).where(Channel.deleted_at.is_(None)))
    ).scalar_one()
    if tracked >= svc.settings.max_channels:
        raise HTTPException(
            422,
            f"You're already tracking {svc.settings.max_channels} channels, the limit. "
            "Remove one to add another.",
        )

    try:
        info = await svc.platforms.get(parsed.platform).resolve(parsed)
    except (ChannelNotFound, NotConfigured) as e:
        raise HTTPException(422, str(e)) from e
    except (PlatformError, httpx.HTTPError) as e:
        raise HTTPException(
            502, f"Couldn't reach {parsed.platform} to look up the channel. Try again."
        ) from e

    existing = (
        await session.execute(
            select(Channel).where(Channel.platform == info.platform, Channel.platform_id == info.platform_id)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.deleted_at is None:
        raise HTTPException(409, f"{existing.display_name} is already tracked.")
    if existing is not None:
        existing.deleted_at = None
        existing.display_name = info.display_name
        existing.thumbnail_url = info.thumbnail_url
        existing.url = info.url
        existing.status = "offline"
        existing.check_failures = 0
        channel = existing
    else:
        channel = Channel(
            platform=info.platform,
            platform_id=info.platform_id,
            url=info.url,
            display_name=info.display_name,
            thumbnail_url=info.thumbnail_url,
        )
        session.add(channel)
    await session.commit()
    svc.poller.kick()
    out = (await views.channels_out(session, [channel.id]))[0]
    svc.bus.publish("channel.updated", out)
    return out


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_channel(
    channel_id: uuid.UUID, session: Session, svc: Svc, stop_recording: Annotated[bool, Query()] = False
):
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        raise HTTPException(404, "That channel isn't tracked.")
    active = (
        (
            await session.execute(
                select(Recording.id).where(
                    Recording.channel_id == channel_id, Recording.status.in_(("recording", "ending"))
                )
            )
        )
        .scalars()
        .all()
    )
    if active and svc.is_viewer:
        raise HTTPException(
            409, f"{channel.display_name} is recording. Remove it from the page on the recording PC."
        )
    if active and not stop_recording:
        raise HTTPException(409, f"{channel.display_name} is recording. Stop the recording to remove it.")
    for rid in active:
        await svc.supervisor.stop_manually(rid)
    channel = await session.get(Channel, channel_id, populate_existing=True)
    channel.deleted_at = utcnow()
    channel.status = "offline"
    await session.commit()
    svc.bus.publish("channel.removed", {"id": str(channel_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
