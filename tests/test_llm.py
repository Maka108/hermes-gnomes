"""Tests for hermes_gnomes.llm — the OpenRouter HTTP client.

Uses httpx.MockTransport to stub out OpenRouter responses without making
real network calls. The tests verify request shape, response parsing,
fallback chain behavior, and error handling.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hermes_gnomes.llm import (
    HAIKU_45_INPUT_USD_PER_MTOK,
    HAIKU_45_OUTPUT_USD_PER_MTOK,
    LLMError,
    LLMResponse,
    OpenRouterClient,
)


def _build_completion_response(
    *,
    text: str = "Hello!",
    model: str = "anthropic/claude-haiku-4.5",
    input_tokens: int = 12,
    output_tokens: int = 5,
) -> dict[str, Any]:
    return {
        "id": "gen-fake-001",
        "model": model,
        "object": "chat.completion",
        "created": 1734120000,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def _make_client(handler) -> OpenRouterClient:
    transport = httpx.MockTransport(handler)
    return OpenRouterClient(
        api_key="sk-or-v1-FAKE_TEST_KEY",
        primary_model="anthropic/claude-haiku-4.5",
        fallback_models=["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5"],
        _transport=transport,
    )


@pytest.mark.asyncio
async def test_complete_returns_text_and_usage() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json=_build_completion_response(text="Hi there.", input_tokens=20, output_tokens=4),
        )

    client = _make_client(handler)
    try:
        response = await client.complete(system="be brief", user="say hi")
    finally:
        await client.aclose()

    assert isinstance(response, LLMResponse)
    assert response.text == "Hi there."
    assert response.model == "anthropic/claude-haiku-4.5"
    assert response.input_tokens == 20
    assert response.output_tokens == 4
    expected_cost = (
        20 / 1_000_000 * HAIKU_45_INPUT_USD_PER_MTOK + 4 / 1_000_000 * HAIKU_45_OUTPUT_USD_PER_MTOK
    )
    assert response.cost_usd == pytest.approx(expected_cost)


@pytest.mark.asyncio
async def test_complete_sends_correct_request_shape() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_build_completion_response())

    client = _make_client(handler)
    try:
        await client.complete(system="sys text", user="user text")
    finally:
        await client.aclose()

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer sk-or-v1-FAKE_TEST_KEY"
    assert "hermes-gnomes" in captured["headers"]["http-referer"].lower()
    assert captured["headers"]["x-title"] == "Hermes Gnomes"

    body = captured["body"]
    assert body["model"] == "anthropic/claude-haiku-4.5"
    assert body["messages"] == [
        {"role": "system", "content": "sys text"},
        {"role": "user", "content": "user text"},
    ]
    assert body["stream"] is False


@pytest.mark.asyncio
async def test_fallback_on_primary_5xx_succeeds_with_secondary() -> None:
    call_count = {"n": 0}
    seen_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_models.append(body["model"])
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(503, json={"error": {"message": "primary down"}})
        return httpx.Response(
            200,
            json=_build_completion_response(model=body["model"], text="fallback ok"),
        )

    client = _make_client(handler)
    try:
        response = await client.complete(system="s", user="u")
    finally:
        await client.aclose()

    assert response.text == "fallback ok"
    assert response.model == "openai/gpt-4o-mini"
    assert seen_models == ["anthropic/claude-haiku-4.5", "openai/gpt-4o-mini"]


@pytest.mark.asyncio
async def test_fallback_on_429_triggers_next_model() -> None:
    seen_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_models.append(body["model"])
        if body["model"] != "anthropic/claude-sonnet-4.5":
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(
            200, json=_build_completion_response(model=body["model"], text="finally")
        )

    client = _make_client(handler)
    try:
        response = await client.complete(system="s", user="u")
    finally:
        await client.aclose()

    assert response.text == "finally"
    assert response.model == "anthropic/claude-sonnet-4.5"
    assert seen_models == [
        "anthropic/claude-haiku-4.5",
        "openai/gpt-4o-mini",
        "anthropic/claude-sonnet-4.5",
    ]


@pytest.mark.asyncio
async def test_all_models_fail_raises_llm_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "everything broken"}})

    client = _make_client(handler)
    try:
        with pytest.raises(LLMError, match="all models failed"):
            await client.complete(system="s", user="u")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_401_does_not_fall_back_and_raises_immediately() -> None:
    """A 401 means the API key is bad — falling back to other models won't help."""
    call_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    client = _make_client(handler)
    try:
        with pytest.raises(LLMError, match="authentication"):
            await client.complete(system="s", user="u")
    finally:
        await client.aclose()

    assert call_count["n"] == 1, "401 should not trigger fallback retries"


@pytest.mark.asyncio
async def test_402_payment_required_raises_immediately() -> None:
    """A 402 means out of credit — falling back won't help either."""
    call_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(402, json={"error": {"message": "insufficient credit"}})

    client = _make_client(handler)
    try:
        with pytest.raises(LLMError, match="credit"):
            await client.complete(system="s", user="u")
    finally:
        await client.aclose()

    assert call_count["n"] == 1, "402 should not trigger fallback retries"


@pytest.mark.asyncio
async def test_canonical_model_name_from_openrouter_still_prices() -> None:
    """OpenRouter returns canonical names with date suffixes
    (e.g. 'anthropic/claude-4.5-haiku-20251001') even when we request the
    alias 'anthropic/claude-haiku-4.5'. The pricing lookup must still find
    Haiku pricing via substring fallback.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_build_completion_response(
                model="anthropic/claude-4.5-haiku-20251001",
                input_tokens=100,
                output_tokens=50,
            ),
        )

    client = _make_client(handler)
    try:
        response = await client.complete(system="s", user="u")
    finally:
        await client.aclose()

    assert response.model == "anthropic/claude-4.5-haiku-20251001"
    expected_cost = (
        100 / 1_000_000 * HAIKU_45_INPUT_USD_PER_MTOK
        + 50 / 1_000_000 * HAIKU_45_OUTPUT_USD_PER_MTOK
    )
    assert response.cost_usd == pytest.approx(expected_cost)
    assert response.cost_usd > 0
