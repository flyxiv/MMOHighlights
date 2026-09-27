"""Chzzk chat over its (unofficial) WebSocket protocol, read-only."""

import asyncio
import json
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import websockets

from app.chat.models import ChatMessage

CMD_PING = 0
CMD_PONG = 10000
CMD_CONNECT = 100
CMD_CHAT = 93101
CMD_DONATION = 93102


def _json_field(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value not in ("", "null"):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def parse_frame(frame: dict) -> list[ChatMessage]:
    cmd = frame.get("cmd")
    if cmd not in (CMD_CHAT, CMD_DONATION):
        return []
    out: list[ChatMessage] = []
    for item in frame.get("bdy") or []:
        profile = _json_field(item.get("profile"))
        extras = _json_field(item.get("extras"))
        ms = item.get("msgTime") or item.get("ctime")
        at = datetime.fromtimestamp(ms / 1000, UTC) if isinstance(ms, int | float) else datetime.now(UTC)
        user = profile.get("nickname") or "(anonymous)"
        text = item.get("msg") or item.get("content") or ""
        role = profile.get("userRoleCode")
        badges = (role,) if role and role != "common_user" else ()
        if cmd == CMD_DONATION or extras.get("payAmount"):
            out.append(ChatMessage(at, user, text, "paid", badges, float(extras.get("payAmount") or 0)))
        else:
            out.append(ChatMessage(at, user, text, "message", badges))
    return out


async def chzzk_chat(chat_channel_id: str, access_token: str) -> AsyncIterator[ChatMessage]:
    server = random.randint(1, 5)
    url = f"wss://kr-ss{server}.chat.naver.com/chat"
    async with websockets.connect(url, ping_interval=None, max_size=2**22) as ws:
        await ws.send(
            json.dumps(
                {
                    "ver": "2",
                    "cmd": CMD_CONNECT,
                    "svcid": "game",
                    "cid": chat_channel_id,
                    "bdy": {"uid": None, "devType": 2001, "accTkn": access_token, "auth": "READ"},
                    "tid": 1,
                }
            )
        )

        async def keepalive() -> None:
            while True:
                await asyncio.sleep(20)
                await ws.send(json.dumps({"ver": "2", "cmd": CMD_PING}))

        ka = asyncio.create_task(keepalive())
        try:
            async for raw in ws:
                frame = json.loads(raw)
                if frame.get("cmd") == CMD_PING:
                    await ws.send(json.dumps({"ver": "2", "cmd": CMD_PONG}))
                    continue
                for msg in parse_frame(frame):
                    yield msg
        finally:
            ka.cancel()
