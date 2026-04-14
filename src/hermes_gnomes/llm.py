"""OpenRouter HTTPS client for Hermes Gnomes.

Single responsibility: take a system prompt + user text, return the LLM's
reply as an LLMResponse. Hides OpenRouter request/response details from
callers and implements a fallback chain so a single model outage doesn't
take the bot offline.

This is Phase 1A scope: synchronous text-in / text-out, no streaming, no
tool calling, no chat history. Phase 1B+ will extend this with conversation
state and tool calls when the approval queue and skill loader land.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

__all__ = [
    "HAIKU_45_INPUT_USD_PER_MTOK",
    "HAIKU_45_OUTPUT_USD_PER_MTOK",
    "LLMError",
    "LLMResponse",
    "OpenRouterClient",
]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Per-million-token pricing in USD. Hard-coded for Phase 1A; Phase 2 will
# pull live pricing from OpenRouter's /models endpoint.
HAIKU_45_INPUT_USD_PER_MTOK = 0.80
HAIKU_45_OUTPUT_USD_PER_MTOK = 4.00
GPT_4O_MINI_INPUT_USD_PER_MTOK = 0.15
GPT_4O_MINI_OUTPUT_USD_PER_MTOK = 0.60
SONNET_45_INPUT_USD_PER_MTOK = 3.00
SONNET_45_OUTPUT_USD_PER_MTOK = 15.00

_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "anthropic/claude-haiku-4.5": (
        HAIKU_45_INPUT_USD_PER_MTOK,
        HAIKU_45_OUTPUT_USD_PER_MTOK,
    ),
    "openai/gpt-4o-mini": (
        GPT_4O_MINI_INPUT_USD_PER_MTOK,
        GPT_4O_MINI_OUTPUT_USD_PER_MTOK,
    ),
    "anthropic/claude-sonnet-4.5": (
        SONNET_45_INPUT_USD_PER_MTOK,
        SONNET_45_OUTPUT_USD_PER_MTOK,
    ),
}


class LLMError(RuntimeError):
    """Raised when the LLM call fails after exhausting the fallback chain
    OR when the failure is non-retryable (auth, payment)."""


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class OpenRouterClient:
    """Async OpenRouter client with model fallback.

    Constructor:
      api_key: OpenRouter key (sk-or-v1-...)
      primary_model: tried first
      fallback_models: tried in order if primary fails with a retryable error
      _transport: optional httpx.MockTransport for testing
    """

    def __init__(
        self,
        *,
        api_key: str,
        primary_model: str,
        fallback_models: list[str],
        _transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._models = [primary_model, *fallback_models]
        self._client = httpx.AsyncClient(
            transport=_transport,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, *, system: str, user: str) -> LLMResponse:
        """Send a single prompt to OpenRouter and return the response.

        Tries each model in order. Falls back on 429 / 5xx / network error.
        Does NOT fall back on 401 (bad key) or 402 (out of credit) — those
        are non-retryable and raise LLMError immediately.
        """
        last_error_msg = "no models attempted"
        for model in self._models:
            try:
                return await self._call_one(model=model, system=system, user=user)
            except _Retryable as e:
                last_error_msg = str(e)
                continue
        raise LLMError(f"all models failed: {last_error_msg}")

    async def _call_one(self, *, model: str, system: str, user: str) -> LLMResponse:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": "https://github.com/Maka108/hermes-gnomes",
            "X-Title": "Hermes Gnomes",
            "Content-Type": "application/json",
        }
        try:
            resp = await self._client.post(OPENROUTER_URL, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise _Retryable(f"network error on {model}: {e}") from e

        if resp.status_code == 401:
            raise LLMError(f"authentication failed (401): {_extract_error(resp)}")
        if resp.status_code == 402:
            raise LLMError(f"insufficient credit (402): {_extract_error(resp)}")
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            raise _Retryable(f"{model} returned {resp.status_code}: {_extract_error(resp)}")
        if resp.status_code != 200:
            raise LLMError(
                f"unexpected status {resp.status_code} from {model}: {_extract_error(resp)}"
            )

        return _parse_completion(resp.json())


class _Retryable(Exception):
    """Internal — signals that the caller should try the next fallback model."""


def _extract_error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                return str(err.get("message", err))
            if err is not None:
                return str(err)
        return resp.text[:200]
    except Exception:
        return resp.text[:200]


def _pricing_for(model: str) -> tuple[float, float] | None:
    """Look up (input, output) per-million-token pricing for a model.

    Tries exact match first, then falls back to substring matching because
    OpenRouter sometimes returns canonical names with date suffixes
    (e.g. ``anthropic/claude-4.5-haiku-20251001``) instead of the alias we
    requested (``anthropic/claude-haiku-4.5``).
    """
    if model in _MODEL_PRICING:
        return _MODEL_PRICING[model]

    model_lower = model.lower()
    if "haiku" in model_lower and "4.5" in model_lower:
        return _MODEL_PRICING["anthropic/claude-haiku-4.5"]
    if "gpt-4o-mini" in model_lower:
        return _MODEL_PRICING["openai/gpt-4o-mini"]
    if "sonnet" in model_lower and "4.5" in model_lower:
        return _MODEL_PRICING["anthropic/claude-sonnet-4.5"]
    return None


def _parse_completion(payload: dict) -> LLMResponse:
    model = payload["model"]
    text = payload["choices"][0]["message"]["content"]
    usage = payload["usage"]
    input_tokens = int(usage["prompt_tokens"])
    output_tokens = int(usage["completion_tokens"])
    pricing = _pricing_for(model)
    if pricing is None:
        cost_usd = 0.0
    else:
        in_per_mtok, out_per_mtok = pricing
        cost_usd = input_tokens / 1_000_000 * in_per_mtok + output_tokens / 1_000_000 * out_per_mtok
    return LLMResponse(
        text=text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
