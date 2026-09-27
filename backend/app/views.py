"""Builds API response models from database rows."""

import uuid
from datetime import timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import schemas
from app.archive import console_url, gcs_uri
from app.config import get_settings
from app.models import Channel, ChatMinute, Recording, Segment
from app.util import ACTIVE_RECORDING_STATUSES, utcnow


def _game_ref(game) -> schemas.GameRef | None:
    return schemas.GameRef.model_validate(game) if game is not None else None


def _tier(tier) -> schemas.TierOut | None:
    return schemas.TierOut.model_validate(tier) if tier is not None else None


def _recording_options():
    return (
        selectinload(Recording.channel),
        selectinload(Recording.game),
        selectinload(Recording.tier),
    )


async def _segment_counts(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    if not ids:
        return {}
    rows = await session.execute(
        select(
            Segment.recording_id,
            func.count(),
            func.count().filter(Segment.status == "uploaded"),
        )
        .where(Segment.recording_id.in_(ids), Segment.kind == "video")
        .group_by(Segment.recording_id)
    )
    return {rid: (closed, uploaded) for rid, closed, uploaded in rows}


def recording_out(rec: Recording, counts: tuple[int, int]) -> schemas.RecordingOut:
    s = get_settings()
    end = rec.ended_at or (rec.ending_since if rec.status == "ending" else None) or utcnow()
    return schemas.RecordingOut(
        id=rec.id,
        channel=schemas.ChannelRef.model_validate(rec.channel),
        title=rec.title,
        status=rec.status,
        started_at=rec.started_at,
        # While "ending", this is when the stream went offline (the page shows "offline 3 min").
        ended_at=rec.ended_at or (rec.ending_since if rec.status == "ending" else None),
        duration_s=max((end - rec.started_at).total_seconds(), 0.0),
        bytes_recorded=rec.bytes_recorded,
        chat_messages=rec.chat_messages,
        segments_closed=counts[0],
        segments_uploaded=counts[1],
        gcs_uri=gcs_uri(s.gcs_bucket, rec.gcs_prefix),
        gcs_console_url=console_url(s.gcs_bucket, rec.gcs_prefix),
        game=_game_ref(rec.game),
        tier=_tier(rec.tier),
        labels_source=rec.labels_source,
        last_error=rec.last_error,
        purged_at=rec.purged_at,
        delete_at=rec.started_at + timedelta(days=s.retention_days),
    )


async def recordings_out(session: AsyncSession, recs: list[Recording]) -> list[schemas.RecordingOut]:
    counts = await _segment_counts(session, [r.id for r in recs])
    return [recording_out(r, counts.get(r.id, (0, 0))) for r in recs]


async def load_recording(session: AsyncSession, rid: uuid.UUID) -> Recording | None:
    return (
        await session.execute(select(Recording).where(Recording.id == rid).options(*_recording_options()))
    ).scalar_one_or_none()


async def recording_by_id(session: AsyncSession, rid: uuid.UUID) -> schemas.RecordingOut | None:
    rec = await load_recording(session, rid)
    if rec is None:
        return None
    return (await recordings_out(session, [rec]))[0]


async def recording_detail(session: AsyncSession, rid: uuid.UUID) -> schemas.RecordingDetailOut | None:
    rec = await load_recording(session, rid)
    if rec is None:
        return None
    base = (await recordings_out(session, [rec]))[0]
    segs = (
        (
            await session.execute(
                select(Segment).where(Segment.recording_id == rid).order_by(Segment.seq.desc(), Segment.kind)
            )
        )
        .scalars()
        .all()
    )
    minutes = (
        (
            await session.execute(
                select(ChatMinute).where(ChatMinute.recording_id == rid).order_by(ChatMinute.minute)
            )
        )
        .scalars()
        .all()
    )
    return schemas.RecordingDetailOut(
        **base.model_dump(),
        platform_stream_id=rec.platform_stream_id,
        quality=rec.quality,
        chat_offset_s=rec.chat_offset_s,
        segments=[schemas.SegmentOut.model_validate(x) for x in segs],
        chat_minutes=[schemas.ChatMinuteOut.model_validate(x) for x in minutes],
    )


async def channels_out(
    session: AsyncSession, channel_ids: list[uuid.UUID] | None = None
) -> list[schemas.ChannelOut]:
    q = (
        select(Channel)
        .where(Channel.deleted_at.is_(None))
        .options(selectinload(Channel.default_game), selectinload(Channel.default_tier))
        .order_by(Channel.created_at)
    )
    if channel_ids is not None:
        q = q.where(Channel.id.in_(channel_ids))
    channels = (await session.execute(q)).scalars().all()
    if not channels:
        return []

    # Latest recording per channel.
    latest = (
        select(Recording.channel_id, func.max(Recording.started_at).label("started_at"))
        .where(Recording.channel_id.in_([c.id for c in channels]))
        .group_by(Recording.channel_id)
        .subquery()
    )
    recs = (
        (
            await session.execute(
                select(Recording)
                .join(
                    latest,
                    and_(
                        Recording.channel_id == latest.c.channel_id,
                        Recording.started_at == latest.c.started_at,
                    ),
                )
                .options(selectinload(Recording.game), selectinload(Recording.tier))
            )
        )
        .scalars()
        .all()
    )
    by_channel = {r.channel_id: r for r in recs}

    out = []
    for c in channels:
        r = by_channel.get(c.id)
        out.append(
            schemas.ChannelOut(
                id=c.id,
                platform=c.platform,
                platform_id=c.platform_id,
                url=c.url,
                display_name=c.display_name,
                thumbnail_url=c.thumbnail_url,
                status=c.status,
                live_title=c.live_title,
                live_category=c.live_category,
                live_started_at=c.last_live_started_at if c.status == "live" else None,
                last_live_ended_at=c.last_live_ended_at,
                last_checked_at=c.last_checked_at,
                check_failures=c.check_failures,
                last_error=c.last_error,
                default_game=_game_ref(c.default_game),
                default_tier=_tier(c.default_tier),
                last_recording_title=r.title if r else None,
                last_recording_game=_game_ref(r.game) if r else None,
                last_recording_tier=_tier(r.tier) if r else None,
                active_recording_id=r.id if r and r.status in ACTIVE_RECORDING_STATUSES else None,
                created_at=c.created_at,
            )
        )
    return out
