"""YouTube live chat through the endpoint the web player's chat box uses (no API quota).

1. Load youtube.com/live_chat?v=<id> for the API key, client version and a continuation token.
2. Poll youtubei/v1/live_chat/get_live_chat with the token; each response has new messages and
   the next token plus how long to wait.

Unofficial and subject to change, like the rest of YouTube's web internals.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx

from app.chat.models import ChatMessage
from app.platforms.base import make_client
from app.platforms.youtube import CONSENT_COOKIES

_API_KEY = re.compile(r'"INNERTUBE_API_KEY":"([^"]+)"')
_CLIENT_VERSION = re.compile(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"')
_INITIAL_DATA = re.compile(
    r'(?:window\["ytInitialData"\]|var ytInitialData)\s*=\s*(\{.+?\})\s*;\s*</script>', re.S
)
_AMOUNT = re.compile(r"[\d.,]+")


class ChatUnavailable(RuntimeError):
    """The video has no live chat (ended, disabled, or members-only)."""


def _text(runs_holder: dict | None) -> str:
    if not runs_holder:
        return ""
    if "simpleText" in runs_holder:
        return runs_holder["simpleText"]
    out = []
    for run in runs_holder.get("runs", []):
        if "text" in run:
            out.append(run["text"])
        elif "emoji" in run:
            emoji = run["emoji"]
            shortcuts = emoji.get("shortcuts") or []
            out.append(shortcuts[0] if emoji.get("isCustomEmoji") and shortcuts else emoji.get("emojiId", ""))
    return "".join(out)


def _amount(text: str) -> float | None:
    m = _AMOUNT.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_item(item: dict) -> ChatMessage | None:
    for kind_key, renderer in item.items():
        r = renderer if isinstance(renderer, dict) else {}
        ts = r.get("timestampUsec")
        at = datetime.fromtimestamp(int(ts) / 1_000_000, UTC) if ts else datetime.now(UTC)
        author = _text(r.get("authorName")) or "(unknown)"
        badges = tuple(
            b.get("liveChatAuthorBadgeRenderer", {}).get("tooltip", "") for b in r.get("authorBadges", [])
        )
        if kind_key == "liveChatTextMessageRenderer":
            return ChatMessage(at, author, _text(r.get("message")), "message", badges)
        if kind_key == "liveChatPaidMessageRenderer":
            amount = _amount(_text(r.get("purchaseAmountText")))
            return ChatMessage(at, author, _text(r.get("message")), "paid", badges, amount)
        if kind_key == "liveChatPaidStickerRenderer":
            return ChatMessage(at, author, "", "paid", badges, _amount(_text(r.get("purchaseAmountText"))))
        if kind_key == "liveChatMembershipItemRenderer":
            text = " ".join(x for x in (_text(r.get("headerSubtext")), _text(r.get("message"))) if x)
            return ChatMessage(at, author, text, "subscription", badges)
        if kind_key == "liveChatSponsorshipsGiftPurchaseAnnouncementRenderer":
            header = r.get("header", {}).get("liveChatSponsorshipsHeaderRenderer", {})
            return ChatMessage(
                at,
                _text(header.get("authorName")) or author,
                _text(header.get("primaryText")),
                "subscription",
            )
    return None


def _next_continuation(block: dict) -> tuple[str | None, float]:
    for c in block.get("continuations", []):
        for data in c.values():
            if isinstance(data, dict) and data.get("continuation"):
                return data["continuation"], float(data.get("timeoutMs", 5000)) / 1000
    return None, 5.0


def parse_chat_page(page: str) -> tuple[str, str, str]:
    """(api key, client version, first continuation) from the live_chat page."""
    key, version, data = _API_KEY.search(page), _CLIENT_VERSION.search(page), _INITIAL_DATA.search(page)
    if not (key and version and data):
        raise ChatUnavailable("The live chat page didn't have the expected data.")
    renderer = json.loads(data.group(1)).get("contents", {}).get("liveChatRenderer")
    if not renderer:
        raise ChatUnavailable("This video has no live chat.")
    continuation, _ = _next_continuation(renderer)
    if not continuation:
        raise ChatUnavailable("This video has no live chat.")
    return key.group(1), version.group(1), continuation


def parse_chat_response(body: dict) -> tuple[list[ChatMessage], str | None, float]:
    block = body.get("continuationContents", {}).get("liveChatContinuation")
    if block is None:
        return [], None, 0.0  # chat is over
    messages = []
    for action in block.get("actions", []):
        item = action.get("addChatItemAction", {}).get("item")
        if item:
            msg = parse_item(item)
            if msg is not None:
                messages.append(msg)
    continuation, wait = _next_continuation(block)
    return messages, continuation, wait


async def youtube_chat(video_id: str, client: httpx.AsyncClient | None = None) -> AsyncIterator[ChatMessage]:
    own = client is None
    client = client or make_client()
    try:
        r = await client.get(
            "https://www.youtube.com/live_chat",
            params={"is_popout": "1", "v": video_id},
            cookies=CONSENT_COOKIES,
        )
        r.raise_for_status()
        key, version, continuation = parse_chat_page(r.text)
        # Messages already in the page are history from before we joined; start from the next batch.
        while continuation:
            r = await client.post(
                "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat",
                params={"key": key, "prettyPrint": "false"},
                json={
                    "context": {"client": {"clientName": "WEB", "clientVersion": version, "hl": "en"}},
                    "continuation": continuation,
                },
            )
            r.raise_for_status()
            messages, continuation, wait = parse_chat_response(r.json())
            for m in messages:
                yield m
            await asyncio.sleep(min(max(wait, 1.0), 10.0))
    finally:
        if own:
            await client.aclose()
