import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.chat.chzzk import parse_frame
from app.chat.logger import ChatWriter
from app.chat.models import ChatMessage
from app.chat.twitch import parse_irc_line
from app.chat.youtube import parse_chat_page, parse_chat_response, parse_item

T0 = datetime(2026, 9, 25, 3, 0, tzinfo=UTC)


def test_twitch_privmsg_with_tags():
    line = (
        "@badges=subscriber/12,premium/1;display-name=Raid\\sFan;tmi-sent-ts=1790301600000 "
        ":raid_fan!raid_fan@raid_fan.tmi.twitch.tv PRIVMSG #raidcaller_jin :KEKW that wipe"
    )
    m = parse_irc_line(line)
    assert m is not None
    assert m.user == "Raid Fan" and m.text == "KEKW that wipe" and m.kind == "message"
    assert m.badges == ("subscriber/12", "premium/1")
    assert m.at == datetime.fromtimestamp(1790301600, UTC)


def test_twitch_cheer_and_sub():
    cheer = parse_irc_line("@bits=100;display-name=a :a!a@a PRIVMSG #c :cheer100 gg")
    assert cheer is not None and cheer.kind == "paid" and cheer.amount == 100
    sub = parse_irc_line(r"@display-name=b;system-msg=b\ssubscribed :tmi.twitch.tv USERNOTICE #c :hype")
    assert sub is not None and sub.kind == "subscription" and sub.text == "b subscribed hype"
    assert parse_irc_line(":tmi.twitch.tv 001 justinfan123 :Welcome") is None


def test_chzzk_chat_and_donation_frames():
    chat = parse_frame(
        {
            "cmd": 93101,
            "bdy": [
                {
                    "msg": "ㅋㅋㅋ",
                    "msgTime": 1790301600000,
                    "profile": json.dumps({"nickname": "은하", "userRoleCode": "common_user"}),
                    "extras": "{}",
                }
            ],
        }
    )
    assert [(m.user, m.text, m.kind) for m in chat] == [("은하", "ㅋㅋㅋ", "message")]
    don = parse_frame(
        {
            "cmd": 93102,
            "bdy": [{"msg": "화이팅", "profile": "null", "extras": json.dumps({"payAmount": 1000})}],
        }
    )
    assert don[0].kind == "paid" and don[0].amount == 1000 and don[0].user == "(anonymous)"
    assert parse_frame({"cmd": 0}) == []


def test_youtube_text_paid_and_membership_items():
    text = parse_item(
        {
            "liveChatTextMessageRenderer": {
                "message": {
                    "runs": [
                        {"text": "gg "},
                        {"emoji": {"emojiId": "🔥"}},
                        {"emoji": {"isCustomEmoji": True, "shortcuts": [":yt:"]}},
                    ]
                },
                "authorName": {"simpleText": "@viewer"},
                "timestampUsec": "1790301600000000",
                "authorBadges": [{"liveChatAuthorBadgeRenderer": {"tooltip": "Member (1 year)"}}],
            }
        }
    )
    assert text is not None and text.text == "gg 🔥:yt:" and text.user == "@viewer"
    assert text.badges == ("Member (1 year)",) and text.at == datetime.fromtimestamp(1790301600, UTC)
    paid = parse_item(
        {
            "liveChatPaidMessageRenderer": {
                "purchaseAmountText": {"simpleText": "₩10,000"},
                "authorName": {"simpleText": "@a"},
                "message": {"runs": [{"text": "화이팅"}]},
            }
        }
    )
    assert paid is not None and paid.kind == "paid" and paid.amount == 10000
    member = parse_item({"liveChatMembershipItemRenderer": {"headerSubtext": {"simpleText": "Welcome!"}}})
    assert member is not None and member.kind == "subscription" and member.text == "Welcome!"
    assert parse_item({"liveChatViewerEngagementMessageRenderer": {}}) is None


def test_youtube_chat_page_and_response():
    data = {
        "contents": {
            "liveChatRenderer": {"continuations": [{"reloadContinuationData": {"continuation": "C1"}}]}
        }
    }
    page = (
        '"INNERTUBE_API_KEY":"KEY","INNERTUBE_CLIENT_VERSION":"2.2026"'
        f'<script>window["ytInitialData"] = {json.dumps(data)};</script>'
    )
    assert parse_chat_page(page) == ("KEY", "2.2026", "C1")
    msgs, cont, wait = parse_chat_response(
        {
            "continuationContents": {
                "liveChatContinuation": {
                    "actions": [
                        {
                            "addChatItemAction": {
                                "item": {
                                    "liveChatTextMessageRenderer": {
                                        "message": {"simpleText": "hi"},
                                        "authorName": {"simpleText": "@b"},
                                    }
                                }
                            }
                        }
                    ],
                    "continuations": [
                        {"invalidationContinuationData": {"continuation": "C2", "timeoutMs": 7000}}
                    ],
                }
            }
        }
    )
    assert [m.text for m in msgs] == ["hi"] and cont == "C2" and wait == 7.0
    assert parse_chat_response({}) == ([], None, 0.0)  # stream over


def test_message_time_is_on_the_video_clock():
    m = ChatMessage(T0 + timedelta(seconds=100), "u", "hi")
    assert m.to_line(T0, chat_offset_s=8.0)["t"] == 108.0


def _lines(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(x) for x in f]


def test_writer_rolls_files_with_video_segments(tmp_path: Path):
    w = ChatWriter(tmp_path, T0, chat_offset_s=0.0, seq=0)
    w.write(ChatMessage(T0 + timedelta(seconds=10), "a", "one"))
    w.write(ChatMessage(T0 + timedelta(seconds=70), "b", "two", "paid", amount=100))
    closed = w.rollover(0)
    assert closed == tmp_path / "chat_00000.jsonl.gz"
    assert [x["text"] for x in _lines(closed)] == ["one", "two"]

    # Segment 1 closes with no chat in it: nothing to upload.
    assert w.rollover(1) is None
    w.write(ChatMessage(T0 + timedelta(seconds=650), "a", "three"))
    assert w.close() == (2, tmp_path / "chat_00002.jsonl.gz")

    assert w.total == 3
    assert w.minutes[0].messages == 1 and w.minutes[1].paid_messages == 1
    assert w.minutes[1].paid_amount == 100 and w.minutes[10].messages == 1


def test_gap_markers_are_written_but_not_counted(tmp_path: Path):
    w = ChatWriter(tmp_path, T0, 0.0, seq=0)
    w.write(ChatMessage(T0, "", "chat connection lost; reconnecting", "gap"))
    assert w.total == 0 and not w.dirty_minutes
    closed = w.close()
    assert closed is not None and _lines(closed[1])[0]["kind"] == "gap"
