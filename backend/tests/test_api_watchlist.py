"""Tests for the watchlist API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.watchlist import router as watchlist_router
from app.database import get_db, init_db
from app.market import PriceCache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Create a temporary SQLite DB and patch DB_PATH."""
    db_file = str(tmp_path / "test_watchlist.db")
    monkeypatch.setattr("app.database.DB_PATH", db_file)
    init_db(db_path=db_file)
    return db_file


@pytest.fixture()
def price_cache():
    """PriceCache with a few test prices."""
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("GOOGL", 175.0)
    cache.update("MSFT", 420.0)
    return cache


@pytest.fixture()
def mock_market_source():
    source = MagicMock()
    source.add_ticker = AsyncMock()
    source.remove_ticker = AsyncMock()
    return source


@pytest.fixture()
def client(temp_db, price_cache, mock_market_source, monkeypatch):
    """TestClient for the watchlist router with mocked dependencies."""
    monkeypatch.setattr("app.database.DB_PATH", temp_db)

    app = FastAPI()
    app.include_router(watchlist_router)
    app.state.price_cache = price_cache
    app.state.market_source = mock_market_source

    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests: GET /api/watchlist
# ---------------------------------------------------------------------------


class TestGetWatchlist:
    def test_returns_default_seeded_tickers(self, client):
        """The seeded DB should have 10 default tickers."""
        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 10
        tickers = [item["ticker"] for item in data]
        assert "AAPL" in tickers
        assert "GOOGL" in tickers

    def test_ticker_with_price_has_correct_fields(self, client):
        """Tickers in the cache should have price, daily_change_pct, direction."""
        resp = client.get("/api/watchlist")
        data = resp.json()
        aapl = next(item for item in data if item["ticker"] == "AAPL")
        assert aapl["price"] == pytest.approx(190.0)
        assert "daily_change_pct" in aapl
        assert aapl["direction"] in ("up", "down", "flat", "unchanged")

    def test_ticker_without_price_has_null_price(self, client):
        """Tickers not in the cache should have price=null."""
        resp = client.get("/api/watchlist")
        data = resp.json()
        # TSLA is in the watchlist but not in the price_cache fixture
        tsla = next((item for item in data if item["ticker"] == "TSLA"), None)
        assert tsla is not None
        assert tsla["price"] is None
        assert tsla["daily_change_pct"] == 0
        assert tsla["direction"] == "unchanged"


# ---------------------------------------------------------------------------
# Tests: POST /api/watchlist
# ---------------------------------------------------------------------------


class TestAddTicker:
    def test_add_valid_ticker(self, client, mock_market_source, temp_db):
        """Adding a new valid ticker should return 201 and add it to the DB."""
        resp = client.post("/api/watchlist", json={"ticker": "PYPL"})
        assert resp.status_code == 201
        assert resp.json()["ticker"] == "PYPL"

        # Verify DB was updated
        with get_db(db_path=temp_db) as conn:
            row = conn.execute(
                "SELECT ticker FROM watchlist WHERE user_id='default' AND ticker='PYPL'"
            ).fetchone()
            assert row is not None

        mock_market_source.add_ticker.assert_called_once_with("PYPL")

    def test_add_duplicate_ticker_returns_422(self, client):
        """Adding a ticker already in the watchlist should return 422."""
        resp = client.post("/api/watchlist", json={"ticker": "AAPL"})
        assert resp.status_code == 422
        assert "already in the watchlist" in resp.json()["detail"]

    def test_add_lowercase_ticker_returns_422(self, client):
        """Lowercase tickers should be rejected (format validation)."""
        resp = client.post("/api/watchlist", json={"ticker": "aapl"})
        assert resp.status_code == 422

    def test_add_too_long_ticker_returns_422(self, client):
        """Tickers longer than 5 characters should be rejected."""
        resp = client.post("/api/watchlist", json={"ticker": "TOOLONG"})
        assert resp.status_code == 422

    def test_add_empty_ticker_returns_422(self, client):
        """Empty ticker string should be rejected."""
        resp = client.post("/api/watchlist", json={"ticker": ""})
        assert resp.status_code == 422

    def test_add_ticker_with_special_chars_returns_422(self, client):
        """Tickers with special characters should be rejected."""
        resp = client.post("/api/watchlist", json={"ticker": "BRK.B"})
        assert resp.status_code == 422

    def test_add_numeric_ticker_is_valid(self, client, mock_market_source):
        """Purely numeric tickers like '1234' should be accepted (format allows digits)."""
        resp = client.post("/api/watchlist", json={"ticker": "1234"})
        assert resp.status_code == 201

    def test_add_single_char_ticker_is_valid(self, client, mock_market_source):
        """Single character tickers are valid per the 1-5 char spec."""
        resp = client.post("/api/watchlist", json={"ticker": "X"})
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Tests: DELETE /api/watchlist/{ticker}
# ---------------------------------------------------------------------------


class TestRemoveTicker:
    def test_remove_existing_ticker(self, client, mock_market_source, temp_db):
        """Removing a watchlist ticker should return 204 and delete from DB."""
        resp = client.delete("/api/watchlist/AAPL")
        assert resp.status_code == 204

        with get_db(db_path=temp_db) as conn:
            row = conn.execute(
                "SELECT ticker FROM watchlist WHERE user_id='default' AND ticker='AAPL'"
            ).fetchone()
            assert row is None

        mock_market_source.remove_ticker.assert_called_once_with("AAPL")

    def test_remove_unknown_ticker_returns_404(self, client):
        """Removing a ticker not in the watchlist should return 404."""
        resp = client.delete("/api/watchlist/UNKNOWN")
        assert resp.status_code == 404

    def test_remove_does_not_call_remove_on_404(self, client, mock_market_source):
        """market_source.remove_ticker should not be called when ticker is not found."""
        client.delete("/api/watchlist/NOTFOUND")
        mock_market_source.remove_ticker.assert_not_called()
