"""LLM client using LiteLLM → OpenRouter with Cerebras inference provider."""

from __future__ import annotations

import os

from app.llm.schemas import ChatResponse, TradeAction

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}

_MOCK_RESPONSE = ChatResponse(
    message=(
        "I've reviewed your portfolio. You have $10,000 in cash ready to deploy. "
        "I'll buy 5 shares of AAPL to get you started — it's the largest holding in our "
        "watchlist and a solid anchor position."
    ),
    trades=[TradeAction(ticker="AAPL", side="buy", quantity=5)],
    watchlist_changes=[],
)


def _is_mock_mode() -> bool:
    return os.environ.get("LLM_MOCK", "").lower() == "true"


def call_llm(messages: list[dict]) -> ChatResponse:
    """Call LLM with structured output. Returns ChatResponse.

    In mock mode (LLM_MOCK=true), returns a fixed deterministic response
    without making any API call.

    Raises on API error when not in mock mode.
    """
    if _is_mock_mode():
        return _MOCK_RESPONSE

    from litellm import completion  # noqa: PLC0415  (lazy import — optional dep)

    response = completion(
        model=MODEL,
        messages=messages,
        response_format=ChatResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
        api_key=os.environ.get("OPENROUTER_API_KEY"),
    )
    content = response.choices[0].message.content
    return ChatResponse.model_validate_json(content)
