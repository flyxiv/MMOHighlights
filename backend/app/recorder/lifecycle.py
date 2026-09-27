"""What the poller should do with a channel after each check. Pure, so it's easy to test."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Action(StrEnum):
    NOTHING = "nothing"
    START = "start"  # new recording
    RESTART_PIPELINE = "restart"  # recording, but the process died while still live
    RESUME = "resume"  # back live during the grace period: same recording continues
    COUNT_OFFLINE = "count_offline"  # offline once; wait for confirmation
    BEGIN_ENDING = "begin_ending"  # offline confirmed: stop the pipeline, start the grace period
    FINALIZE = "finalize"  # grace period over


@dataclass(frozen=True)
class RecordingState:
    status: str
    offline_polls: int
    ending_since: datetime | None
    pipeline_running: bool


def decide(
    *,
    is_live: bool,
    stream_id: str | None,
    skip_stream_id: str | None,
    recording: RecordingState | None,
    now: datetime,
    offline_polls_to_end: int,
    grace_period_s: float,
) -> Action:
    if recording is None or recording.status in ("finalizing", "completed", "failed"):
        if is_live and not (stream_id is not None and stream_id == skip_stream_id):
            return Action.START
        return Action.NOTHING

    if recording.status == "recording":
        if is_live:
            return Action.NOTHING if recording.pipeline_running else Action.RESTART_PIPELINE
        if recording.offline_polls + 1 >= offline_polls_to_end:
            return Action.BEGIN_ENDING
        return Action.COUNT_OFFLINE

    if recording.status == "ending":
        if is_live:
            return Action.RESUME
        since = recording.ending_since or now
        if (now - since).total_seconds() >= grace_period_s:
            return Action.FINALIZE
        return Action.NOTHING

    return Action.NOTHING
