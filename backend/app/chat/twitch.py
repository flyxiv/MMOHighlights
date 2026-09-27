"""Twitch chat over IRC-on-WebSocket as an anonymous reader."""

import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import websockets

from app.chat.models import ChatMessage

IRC_URL = "wss://irc-ws.chat.twitch.tv:443"

_TAG_UNESCAPE = {r"\s": " ", r"\:": ";", r"\\": "\\", r"\r": "\r", r"\n": "\n"}


def _unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        pair = value[i : i + 2]
        if pair in _TAG_UNESCAPE:
            out.append(_TAG_UNESCAPE[pair])
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def parse_irc_line(line: str) -> ChatMessage | None:
    tags: dict[str, str] = {}
    rest = line
    if rest.startswith("@"):
        raw_tags, _, rest = rest[1:].partition(" ")
        for kv in raw_tags.split(";"):
            k, _, v = kv.partition("=")
            tags[k] = _unescape(v)
    prefix = ""
    if rest.startswith(":"):
        prefix, _, rest = rest[1:].partition(" ")
    command, _, params = rest.partition(" ")
    if command not in ("PRIVMSG", "USERNOTICE"):
        return None
    _, _, text = params.partition(" :")
    nick = prefix.split("!", 1)[0]
    user = tags.get("display-name") or tags.get("login") or nick
    ts = tags.get("tmi-sent-ts")
    at = datetime.fromtimestamp(int(ts) / 1000, UTC) if ts and ts.isdigit() else datetime.now(UTC)
    badges = tuple(b for b in tags.get("badges", "").split(",") if b)
    if command == "USERNOTICE":
        system = tags.get("system-msg", "")
        return ChatMessage(at, user, f"{system} {text}".strip(), "subscription", badges)
    bits = tags.get("bits")
    if bits and bits.isdigit():
        return ChatMessage(at, user, text, "paid", badges, float(bits))
    return ChatMessage(at, user, text, "message", badges)


async def twitch_chat(login: str) -> AsyncIterator[ChatMessage]:
    async with websockets.connect(IRC_URL, ping_interval=60, max_size=2**20) as ws:
        await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        await ws.send("PASS SCHMOOPIIE")
        await ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
        await ws.send(f"JOIN #{login.lower()}")
        async for frame in ws:
            data = frame if isinstance(frame, str) else frame.decode("utf-8", "replace")
            for line in data.split("\r\n"):
                if not line:
                    continue
                if line.startswith("PING"):
                    await ws.send("PONG" + line[4:])
                    continue
                if " RECONNECT" in line:
                    return
                msg = parse_irc_line(line)
                if msg is not None:
                    yield msg
