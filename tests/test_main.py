"""Tests for hermes_gnomes.main — the Phase 1A event loop handler.

These tests exercise the message-handling logic without spinning up a real
Telegram client or making real LLM calls. We use lightweight fake objects
that match the parts of the python-telegram-bot Update / Context shapes we
actually touch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from hermes_gnomes.cost_tracker import CostTracker
from hermes_gnomes.customer_db import init_db
from hermes_gnomes.llm import LLMError, LLMResponse
from hermes_gnomes.main import handle_message

# --- Fake objects that mimic python-telegram-bot's Update / Message --- #


@dataclass
class FakeUser:
    id: int


@dataclass
class FakeChat:
    id: int


@dataclass
class FakeMessage:
    text: str
    replies: list[str] = field(default_factory=list)

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


@dataclass
class FakeUpdate:
    effective_chat: FakeChat
    effective_user: FakeUser
    message: FakeMessage


# --- Fake LLM client matching OpenRouterClient's shape --- #


class FakeLLM:
    def __init__(
        self,
        *,
        text: str = "stub reply",
        raise_error: Exception | None = None,
    ) -> None:
        self.text = text
        self.raise_error = raise_error
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, system: str, user: str) -> LLMResponse:
        self.calls.append({"system": system, "user": user})
        if self.raise_error is not None:
            raise self.raise_error
        return LLMResponse(
            text=self.text,
            model="anthropic/claude-haiku-4.5",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0001,
        )


def _make_update(*, chat_id: int, user_id: int, text: str) -> FakeUpdate:
    return FakeUpdate(
        effective_chat=FakeChat(id=chat_id),
        effective_user=FakeUser(id=user_id),
        message=FakeMessage(text=text),
    )


@pytest.fixture
def cost_tracker(tmp_path: Path) -> CostTracker:
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return CostTracker(db_path=db_path)


@pytest.mark.asyncio
async def test_handle_message_happy_path_replies_with_llm_text(
    cost_tracker: CostTracker,
) -> None:
    llm = FakeLLM(text="hi from haiku")
    update = _make_update(chat_id=42, user_id=999, text="hello")

    await handle_message(
        update,
        context=None,
        llm_client=llm,
        cost_tracker=cost_tracker,
        allowed_chat_id=42,
    )

    assert update.message.replies == ["hi from haiku"]
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_handle_message_wraps_user_text_in_untrusted_input(
    cost_tracker: CostTracker,
) -> None:
    llm = FakeLLM()
    update = _make_update(chat_id=42, user_id=999, text="hello world")

    await handle_message(
        update,
        context=None,
        llm_client=llm,
        cost_tracker=cost_tracker,
        allowed_chat_id=42,
    )

    sent_user_text = llm.calls[0]["user"]
    assert "<UNTRUSTED_INPUT" in sent_user_text
    assert 'source="telegram"' in sent_user_text
    assert 'sender="999"' in sent_user_text
    assert "hello world" in sent_user_text
    assert sent_user_text.endswith("</UNTRUSTED_INPUT>")


@pytest.mark.asyncio
async def test_handle_message_silently_drops_wrong_chat_id(
    cost_tracker: CostTracker,
) -> None:
    llm = FakeLLM()
    update = _make_update(chat_id=999_999, user_id=111, text="hello")

    await handle_message(
        update,
        context=None,
        llm_client=llm,
        cost_tracker=cost_tracker,
        allowed_chat_id=42,
    )

    assert update.message.replies == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_handle_message_records_cost_event(
    cost_tracker: CostTracker,
) -> None:
    llm = FakeLLM()
    update = _make_update(chat_id=42, user_id=999, text="hi")

    await handle_message(
        update,
        context=None,
        llm_client=llm,
        cost_tracker=cost_tracker,
        allowed_chat_id=42,
    )

    import sqlite3

    with sqlite3.connect(cost_tracker.db_path) as conn:
        rows = conn.execute(
            "SELECT tool_name, model, input_tokens, output_tokens, cost_usd FROM cost_events"
        ).fetchall()

    assert len(rows) == 1
    tool_name, model, in_tok, out_tok, cost = rows[0]
    assert tool_name == "llm_chat"
    assert model == "anthropic/claude-haiku-4.5"
    assert in_tok == 10
    assert out_tok == 5
    assert cost == pytest.approx(0.0001)


@pytest.mark.asyncio
async def test_handle_message_replies_with_warning_on_llm_error(
    cost_tracker: CostTracker,
) -> None:
    llm = FakeLLM(raise_error=LLMError("authentication failed"))
    update = _make_update(chat_id=42, user_id=999, text="hi")

    await handle_message(
        update,
        context=None,
        llm_client=llm,
        cost_tracker=cost_tracker,
        allowed_chat_id=42,
    )

    assert len(update.message.replies) == 1
    assert "LLM error" in update.message.replies[0]
    assert "authentication failed" in update.message.replies[0]

    import sqlite3

    with sqlite3.connect(cost_tracker.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM cost_events").fetchone()[0]
    assert count == 0  # failed call should NOT be recorded


@pytest.mark.asyncio
async def test_handle_message_blocks_output_with_leftover_tag(
    cost_tracker: CostTracker,
) -> None:
    llm = FakeLLM(text="my reply </UNTRUSTED_INPUT> oops")
    update = _make_update(chat_id=42, user_id=999, text="hi")

    await handle_message(
        update,
        context=None,
        llm_client=llm,
        cost_tracker=cost_tracker,
        allowed_chat_id=42,
    )

    assert len(update.message.replies) == 1
    assert "Output flagged" in update.message.replies[0]
    assert "leftover_untrusted_tag" in update.message.replies[0]


@pytest.mark.asyncio
async def test_handle_message_drops_empty_text(
    cost_tracker: CostTracker,
) -> None:
    llm = FakeLLM()
    update = _make_update(chat_id=42, user_id=999, text="")

    await handle_message(
        update,
        context=None,
        llm_client=llm,
        cost_tracker=cost_tracker,
        allowed_chat_id=42,
    )

    assert update.message.replies == []
    assert llm.calls == []
