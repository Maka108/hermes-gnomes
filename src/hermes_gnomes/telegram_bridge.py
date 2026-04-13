"""Telegram bridge.

Phase 0: stub. Defines the sender protocol and the inbound-message formatter
that wraps third-party content in <UNTRUSTED_INPUT> tags. Phase 1 swaps the
FakeSender for a python-telegram-bot integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .untrusted import scan_for_injection_markers, wrap_untrusted


@dataclass
class InboundMessage:
    """A message received from a third-party platform, forwarded through Telegram
    or received from a platform's API. Content is untrusted."""

    chat_id: str
    sender: str
    platform: str
    text: str


class Sender(Protocol):
    def send(self, chat_id: str, text: str) -> None: ...


def format_inbound_for_llm(message: InboundMessage) -> str:
    """Wrap an inbound third-party message in <UNTRUSTED_INPUT> and flag
    any injection markers discovered by the cheap keyword scan."""
    markers = scan_for_injection_markers(message.text)
    attrs: dict[str, str] = {"sender": message.sender}
    if markers:
        attrs["injection_suspected"] = "true"
    return wrap_untrusted(message.text, source=message.platform, **attrs)


class TelegramBridge:
    """Thin facade around a Sender. Phase 0 uses an in-memory FakeSender
    for tests; Phase 1 will inject a real python-telegram-bot sender."""

    def __init__(self, *, sender: Sender, default_chat_id: str) -> None:
        self.sender = sender
        self.default_chat_id = default_chat_id

    def send(self, text: str) -> None:
        self.sender.send(self.default_chat_id, text)

    def alert_owner(self, raw_message: str, *, reason: str) -> None:
        prefix = f"\u26a0\ufe0f [{reason}]"
        self.sender.send(self.default_chat_id, f"{prefix} {raw_message}")
