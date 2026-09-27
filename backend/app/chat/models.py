from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Kind = Literal["message", "paid", "subscription", "gap"]


@dataclass(frozen=True)
class ChatMessage:
    at: datetime
    user: str
    text: str
    kind: Kind = "message"
    badges: tuple[str, ...] = field(default_factory=tuple)
    # Bits, Super Chat amount or Chzzk cheese, in the platform's own unit.
    amount: float | None = None

    def to_line(self, recording_start: datetime, chat_offset_s: float) -> dict:
        t = (self.at - recording_start).total_seconds() + chat_offset_s
        return {
            "t": round(t, 3),
            "at": self.at.isoformat(timespec="milliseconds"),
            "user": self.user,
            "text": self.text,
            "kind": self.kind,
            "badges": list(self.badges),
            "amount": self.amount,
        }
