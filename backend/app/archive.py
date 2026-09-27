"""Where recordings live in the bucket, and the manifest/playlist written next to them."""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from app.util import slugify


def recording_prefix(
    base_prefix: str, platform: str, platform_id: str, started_at: datetime, recording_id
) -> str:
    """archives/twitch/raidcaller_jin/2026-09-25/<uuid>/"""
    return f"{base_prefix}{platform}/{slugify(platform_id)}/{started_at:%Y-%m-%d}/{recording_id}/"


def gcs_uri(bucket: str, prefix: str) -> str:
    return f"gs://{bucket}/{prefix}"


def console_url(bucket: str, prefix: str) -> str:
    return f"https://console.cloud.google.com/storage/browser/{bucket}/{quote(prefix.rstrip('/'))}"


def video_name(seq: int) -> str:
    return f"seg_{seq:05d}.ts"


def chat_name(seq: int) -> str:
    return f"chat_{seq:05d}.jsonl.gz"


@dataclass
class UploadedVideo:
    seq: int
    start_s: float | None
    end_s: float | None
    size_bytes: int


def build_playlist(segments: list[UploadedVideo], finished: bool) -> str:
    """HLS VOD playlist over the uploaded .ts files, so the bucket folder plays directly."""
    durations = [max((s.end_s or 0) - (s.start_s or 0), 0.0) for s in segments]
    target = max([math.ceil(d) for d in durations] or [1])
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target}",
        f"#EXT-X-MEDIA-SEQUENCE:{segments[0].seq if segments else 0}",
        f"#EXT-X-PLAYLIST-TYPE:{'VOD' if finished else 'EVENT'}",
    ]
    prev = None
    for s, d in zip(segments, durations, strict=True):
        if prev is not None and s.seq != prev + 1:
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append(f"#EXTINF:{d:.3f},")
        lines.append(video_name(s.seq))
        prev = s.seq
    if finished:
        lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def build_manifest(recording: dict[str, Any], segments: list[UploadedVideo], chat_files: list[int]) -> str:
    body = {
        **recording,
        "segments": [
            {
                "seq": s.seq,
                "file": video_name(s.seq),
                "start_s": s.start_s,
                "end_s": s.end_s,
                "size_bytes": s.size_bytes,
            }
            for s in segments
        ],
        "chat_files": [chat_name(seq) for seq in chat_files],
    }
    return json.dumps(body, ensure_ascii=False, indent=2, default=str)
