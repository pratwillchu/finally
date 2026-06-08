"""Unit tests for the LLM chat integration.

All tests run with LLM_MOCK=true so no real API calls are made.
"""

from __future__ import annotations

import os

import pytest

# Ensure mock mode is active before any imports that might read the env
os.environ["LLM_MOCK"] = "true"

from app.database import get_db, init_db  # noqa: E402
from app.llm.client import call_llm  # noqa: E402
from app.llm.schemas import ChatResponse, TradeAction, WatchlistAction  # noqa: E402
from app.market import PriceCache  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────


class MockPriceCache:
    """Minimal PriceCache-compatible mock for testing."""

    def get_price(self, ticker: str) -> float:
        return 190.0

    def get_all(self) -> dict:
        return {}

    def get(self, ticker: str):
        return None  # OK — not used in mock mode


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_mock_response():
    """call_llm returns the fixed mock ChatResponse when LLM_MOCK=true."""
    response = call_llm([])
    assert isinstance(response, ChatResponse)
    assert len(response.trades) == 1
    trade = response.trades[0]
    assert trade.ticker == "AAPL"
    assert trade.side == "buy"
    assert trade.quantity == 5


def test_chatresponse_schema():
    """ChatResponse parses valid JSON correctly."""
    data = """
    {
        "message": "Hello from the assistant",
        "trades": [{"ticker": "MSFT", "side": "buy", "quantity": 10.0}],
        "watchlist_changes": [{"ticker": "TSLA", "action": "add"}]
    }
    """
    resp = ChatResponse.model_validate_json(data)
    assert resp.message == "Hello from the assistant"
    assert len(resp.trades) == 1
    assert resp.trades[0].ticker == "MSFT"
    assert resp.trades[0].side == "buy"
    assert resp.trades[0].quantity == 10.0
    assert len(resp.watchlist_changes) == 1
    assert resp.watchlist_changes[0].ticker == "TSLA"
    assert resp.watchlist_changes[0].action == "add"


def test_chatresponse_defaults():
    """ChatResponse has empty lists as defaults for optional fields."""
    resp = ChatResponse.model_validate_json('{"message": "hi"}')
    assert resp.trades == []
    assert resp.watchlist_changes == []


def test_trade_action_schema():
    """TradeAction validates all required fields."""
    ta = TradeAction(ticker="NVDA", side="sell", quantity=3.5)
    assert ta.ticker == "NVDA"
    assert ta.side == "sell"
    assert ta.quantity == 3.5


def test_watchlist_action_schema():
    """WatchlistAction validates action field."""
    wa = WatchlistAction(ticker="GOOGL", action="remove")
    assert wa.ticker == "GOOGL"
    assert wa.action == "remove"


def test_handle_chat_mock(tmp_path):
    """Full handle_chat() with mock data: returns expected shape and executes AAPL buy."""
    from app.llm.chat_handler import handle_chat

    # Initialize a temp SQLite DB
    db_path = tmp_path / "test.db"
    init_db(db_path)

    price_cache = MockPriceCache()

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        result = handle_chat("Hello, what should I buy?", price_cache, conn)
    finally:
        conn.close()

    # Verify response shape
    assert "message" in result
    assert "trades" in result
    assert "watchlist_changes" in result
    assert "errors" in result
    assert isinstance(result["message"], str)
    assert len(result["message"]) > 0

    # Verify AAPL trade was recorded in trades table
    conn2 = sqlite3.connect(str(db_path))
    conn2.row_factory = sqlite3.Row
    try:
        trades = conn2.execute(
            "SELECT * FROM trades WHERE ticker='AAPL' AND side='buy'"
        ).fetchall()
        assert len(trades) >= 1
        assert trades[0]["quantity"] == 5
        assert trades[0]["price"] == 190.0
    finally:
        conn2.close()


def test_handle_chat_saves_messages(tmp_path):
    """handle_chat() saves both user and assistant messages to chat_messages."""
    from app.llm.chat_handler import handle_chat

    db_path = tmp_path / "test_msgs.db"
    init_db(db_path)

    price_cache = MockPriceCache()

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        handle_chat("What's my portfolio looking like?", price_cache, conn)
    finally:
        conn.close()

    # Verify messages saved
    conn2 = sqlite3.connect(str(db_path))
    conn2.row_factory = sqlite3.Row
    try:
        messages = conn2.execute(
            "SELECT role, content FROM chat_messages WHERE user_id='default' ORDER BY created_at ASC"
        ).fetchall()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What's my portfolio looking like?"
        assert messages[1]["role"] == "assistant"
        assert len(messages[1]["content"]) > 0
    finally:
        conn2.close()


def test_handle_chat_conversation_history(tmp_path):
    """handle_chat() loads prior conversation history for context."""
    from app.llm.chat_handler import handle_chat

    db_path = tmp_path / "test_history.db"
    init_db(db_path)

    price_cache = MockPriceCache()

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # Two sequential messages
        handle_chat("First message", price_cache, conn)
        handle_chat("Second message", price_cache, conn)
    finally:
        conn.close()

    # Verify 4 messages saved (2 user + 2 assistant)
    conn2 = sqlite3.connect(str(db_path))
    conn2.row_factory = sqlite3.Row
    try:
        messages = conn2.execute(
            "SELECT role FROM chat_messages WHERE user_id='default' ORDER BY created_at ASC"
        ).fetchall()
        assert len(messages) == 4
        assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    finally:
        conn2.close()


def test_mock_mode_flag():
    """When LLM_MOCK=false and no API key, client should attempt real call (not silently mock)."""
    from app.llm import client as llm_client

    # Temporarily disable mock mode
    original = os.environ.get("LLM_MOCK", "")
    os.environ["LLM_MOCK"] = "false"
    os.environ.pop("OPENROUTER_API_KEY", None)

    try:
        # _is_mock_mode() should return False
        assert not llm_client._is_mock_mode()
    finally:
        os.environ["LLM_MOCK"] = original
