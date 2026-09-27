"""JSON shapes of the HTTP API. The frontend mirrors these in frontend/lib/types.ts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Platform = Literal["twitch", "youtube", "chzzk"]
ChannelStatus = Literal["offline", "live", "error"]
RecordingStatus = Literal["recording", "ending", "finalizing", "completed", "failed"]
SegmentStatus = Literal["pending", "uploading", "uploaded", "failed"]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TierOut(_Out):
    id: int
    game_id: int
    name: str
    archived: bool


class GameOut(_Out):
    id: int
    name: str
    tiers: list[TierOut] = []


class GameRef(_Out):
    id: int
    name: str


class ChannelOut(_Out):
    id: uuid.UUID
    platform: Platform
    platform_id: str
    url: str
    display_name: str
    thumbnail_url: str | None
    status: ChannelStatus
    live_title: str | None
    live_category: str | None
    live_started_at: datetime | None = Field(description="Set while live.")
    last_live_ended_at: datetime | None
    last_checked_at: datetime | None
    check_failures: int
    last_error: str | None
    default_game: GameRef | None
    default_tier: TierOut | None
    # Title and labels of the running recording, or of the most recent one when offline.
    last_recording_title: str | None
    last_recording_game: GameRef | None
    last_recording_tier: TierOut | None
    active_recording_id: uuid.UUID | None
    created_at: datetime


class ChannelCreate(BaseModel):
    url: str


class ChannelRef(_Out):
    id: uuid.UUID
    platform: Platform
    display_name: str
    thumbnail_url: str | None


class RecordingOut(_Out):
    id: uuid.UUID
    channel: ChannelRef
    title: str
    status: RecordingStatus
    started_at: datetime
    ended_at: datetime | None
    duration_s: float
    bytes_recorded: int
    chat_messages: int
    segments_closed: int = Field(description="Closed video segments.")
    segments_uploaded: int = Field(description="Uploaded video segments.")
    gcs_uri: str
    gcs_console_url: str
    game: GameRef | None
    tier: TierOut | None
    labels_source: Literal["manual", "channel_default", "suggested"] | None
    last_error: str | None
    purged_at: datetime | None
    delete_at: datetime


class SegmentOut(_Out):
    kind: Literal["video", "chat"]
    seq: int
    start_s: float | None
    end_s: float | None
    size_bytes: int
    status: SegmentStatus
    attempts: int
    uploaded_at: datetime | None


class ChatMinuteOut(_Out):
    minute: int
    messages: int
    unique_chatters: int
    paid_messages: int


class RecordingDetailOut(RecordingOut):
    platform_stream_id: str | None
    quality: str | None
    chat_offset_s: float
    segments: list[SegmentOut]
    chat_minutes: list[ChatMinuteOut]


class RecordingPage(BaseModel):
    items: list[RecordingOut]
    total: int
    page: int
    page_size: int


class RecordingLabels(BaseModel):
    game_id: int | None
    tier_id: int | None


class GameCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class TierCreate(BaseModel):
    game_id: int
    name: str = Field(min_length=1, max_length=128)


class TierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    archived: bool | None = None


class HealthOut(BaseModel):
    poll_last_run_at: datetime | None
    next_poll_in_s: float | None
    spool_free_bytes: int
    upload_backlog: int
    tracked_count: int
    max_channels: int
    live_count: int
    recording_count: int
    chat_messages_active: int
    bytes_active: int
