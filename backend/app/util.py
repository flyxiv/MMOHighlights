import re
from datetime import UTC, datetime

ACTIVE_RECORDING_STATUSES = ("recording", "ending", "finalizing")


def utcnow() -> datetime:
    return datetime.now(UTC)


def upload_backoff_s(attempts: int) -> float:
    """10 s, 20 s, 40 s … capped at one hour."""
    return float(min(10 * 2 ** max(attempts - 1, 0), 3600))


def slugify(text: str) -> str:
    # Case is kept: YouTube channel ids are case-sensitive.
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-")
    return s or "channel"
