import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _enum(*values: str, name: str) -> Enum:
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=16)


PLATFORMS = ("twitch", "youtube", "chzzk")
CHANNEL_STATUSES = ("offline", "live", "error")
# recording  – pipeline running
# ending     – stream offline, waiting out the grace period (may resume)
# finalizing – grace period over, remaining segments uploading
RECORDING_STATUSES = ("recording", "ending", "finalizing", "completed", "failed")
SEGMENT_KINDS = ("video", "chat")
SEGMENT_STATUSES = ("pending", "uploading", "uploaded", "failed")
LABEL_SOURCES = ("manual", "channel_default", "suggested")


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)

    tiers: Mapped[list["Tier"]] = relationship(back_populates="game", order_by="Tier.id")


class Tier(Base):
    __tablename__ = "tiers"
    __table_args__ = (UniqueConstraint("game_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    game: Mapped[Game] = relationship(back_populates="tiers")


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("platform", "platform_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(_enum(*PLATFORMS, name="platform"))
    platform_id: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(String(256))
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(_enum(*CHANNEL_STATUSES, name="channel_status"), default="offline")
    live_title: Mapped[str | None] = mapped_column(Text)
    live_category: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_live_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_live_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    default_game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    default_tier_id: Mapped[int | None] = mapped_column(ForeignKey("tiers.id", ondelete="SET NULL"))
    # Set when you stop a recording by hand, so the poller doesn't restart the same broadcast.
    skip_stream_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Removed channels are kept so their recordings still show a channel name.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    default_game: Mapped["Game | None"] = relationship(foreign_keys=[default_game_id])
    default_tier: Mapped["Tier | None"] = relationship(foreign_keys=[default_tier_id])


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (Index("ix_recordings_status_started", "status", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    platform_stream_id: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(_enum(*RECORDING_STATUSES, name="recording_status"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offline_polls: Mapped[int] = mapped_column(Integer, default=0)
    gcs_prefix: Mapped[str] = mapped_column(Text)
    quality: Mapped[str | None] = mapped_column(String(32))
    bytes_recorded: Mapped[int] = mapped_column(BigInteger, default=0)
    chat_messages: Mapped[int] = mapped_column(Integer, default=0)
    chat_offset_s: Mapped[float] = mapped_column(Float, default=0.0)
    last_error: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    tier_id: Mapped[int | None] = mapped_column(ForeignKey("tiers.id", ondelete="SET NULL"))
    labels_source: Mapped[str | None] = mapped_column(_enum(*LABEL_SOURCES, name="labels_source"))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    channel: Mapped[Channel] = relationship()
    game: Mapped[Game | None] = relationship()
    tier: Mapped[Tier | None] = relationship()


class Segment(Base):
    """A closed video or chat file. The table doubles as the upload queue."""

    __tablename__ = "segments"
    __table_args__ = (
        Index(
            "ix_segments_pending",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(_enum(*SEGMENT_KINDS, name="segment_kind"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    local_path: Mapped[str] = mapped_column(Text)
    start_s: Mapped[float | None] = mapped_column(Float)
    end_s: Mapped[float | None] = mapped_column(Float)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(_enum(*SEGMENT_STATUSES, name="segment_status"), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMinute(Base):
    __tablename__ = "chat_minutes"

    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), primary_key=True
    )
    minute: Mapped[int] = mapped_column(Integer, primary_key=True)
    messages: Mapped[int] = mapped_column(Integer, default=0)
    unique_chatters: Mapped[int] = mapped_column(Integer, default=0)
    paid_messages: Mapped[int] = mapped_column(Integer, default=0)
    paid_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
