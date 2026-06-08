"""Tests for the portfolio API routes."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.portfolio import router as portfolio_router
from app.database import get_db, init_db
from app.market import PriceCache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Create a temporary SQLite DB and patch DB_PATH so all calls use it."""
    db_file = str(tmp_path / "test_finally.db")
    monkeypatch.setattr("app.database.DB_PATH", db_file)
    init_db(db_path=db_file)
    return db_file


@pytest.fixture()
def price_cache():
    """A PriceCache pre-seeded with a couple of test prices."""
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("GOOGL", 175.0)
    return cache


@pytest.fixture()
def mock_market_source():
    source = MagicMock()
    source.add_ticker = AsyncMock()
    source.remove_ticker = AsyncMock()
    return source


@pytest.fixture()
def test_app(temp_db, price_cache, mock_market_source):
    """FastAPI test app with portfolio router, mocked state."""
    app = FastAPI()
    app.include_router(portfolio_router)

    app.state.price_cache = price_cache
    app.state.market_source = mock_market_source

    # Patch get_db inside portfolio routes to use the temp DB
    import app.api.portfolio as portfolio_module
    original_get_db = portfolio_module.get_db

    from contextlib import contextmanager

    @contextmanager
    def patched_get_db(db_path=None):
        with original_get_db(db_path=temp_db):
            yield _conn_from_temp(temp_db)

    return app, temp_db


def _conn_from_temp(db_path: str):
    """Not used directly — helper for clarity."""
    pass


@pytest.fixture()
def client(temp_db, price_cache, mock_market_source, monkeypatch):
    """TestClient configured with a temp DB and mocked market state."""
    # Patch DB_PATH in the portfolio module too
    monkeypatch.setattr("app.database.DB_PATH", temp_db)

    app = FastAPI()
    app.include_router(portfolio_router)
    app.state.price_cache = price_cache
    app.state.market_source = mock_market_source

    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests: GET /api/portfolio
# ---------------------------------------------------------------------------


class TestGetPortfolio:
    def test_empty_portfolio_returns_cash_and_no_positions(self, client):
        """With no positions, should return $10k cash and empty positions list."""
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cash_balance"] == pytest.approx(10000.0, abs=0.01)
        assert data["total_value"] == pytest.approx(10000.0, abs=0.01)
        assert data["positions"] == []

    def test_portfolio_with_position(self, client, temp_db):
        """After manually inserting a position, it should appear in the response."""
        import uuid
        from datetime import datetime

        with get_db(db_path=temp_db) as conn:
            conn.execute(
                "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                "VALUES (?, 'default', 'AAPL', 5.0, 180.0, ?)",
                (str(uuid.uuid4()), datetime.utcnow().isoformat()),
            )
            conn.execute(
                "UPDATE users_profile SET cash_balance=9100.0 WHERE id='default'"
            )
            conn.commit()

        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["positions"]) == 1
        pos = data["positions"][0]
        assert pos["ticker"] == "AAPL"
        assert pos["quantity"] == 5.0
        assert pos["avg_cost"] == pytest.approx(180.0)
        assert pos["current_price"] == pytest.approx(190.0)  # from cache
        assert pos["unrealized_pnl"] == pytest.approx(50.0)  # (190-180)*5
        assert pos["pnl_pct"] == pytest.approx(5.5556, abs=0.01)


# ---------------------------------------------------------------------------
# Tests: POST /api/portfolio/trade
# ---------------------------------------------------------------------------


class TestTrade:
    def test_buy_succeeds_and_reduces_cash(self, client, temp_db):
        """Buying 5 AAPL at $190 should deduct $950 from cash."""
        resp = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy", "quantity": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["side"] == "buy"
        assert data["quantity"] == 5.0
        assert data["price"] == pytest.approx(190.0)

        # Verify cash was deducted
        with get_db(db_path=temp_db) as conn:
            profile = conn.execute("SELECT cash_balance FROM users_profile WHERE id='default'").fetchone()
            assert profile["cash_balance"] == pytest.approx(10000.0 - 950.0, abs=0.01)

    def test_sell_succeeds_after_buy(self, client, temp_db):
        """Selling shares acquired in a prior buy should increase cash."""
        # Buy first
        client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy", "quantity": 5})

        resp = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "sell", "quantity": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["side"] == "sell"
        assert data["quantity"] == 3.0

        with get_db(db_path=temp_db) as conn:
            pos = conn.execute(
                "SELECT quantity FROM positions WHERE user_id='default' AND ticker='AAPL'"
            ).fetchone()
            assert pos["quantity"] == pytest.approx(2.0)

    def test_sell_all_removes_position_row(self, client, temp_db):
        """Selling exactly all shares should delete the position row."""
        client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy", "quantity": 5})
        resp = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "sell", "quantity": 5})
        assert resp.status_code == 200

        with get_db(db_path=temp_db) as conn:
            pos = conn.execute(
                "SELECT id FROM positions WHERE user_id='default' AND ticker='AAPL'"
            ).fetchone()
            assert pos is None

    def test_buy_insufficient_cash_returns_400(self, client):
        """Trying to buy more than cash allows should return 400."""
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "side": "buy", "quantity": 100},
        )
        assert resp.status_code == 400
        assert "Insufficient cash" in resp.json()["detail"]

    def test_sell_more_than_owned_returns_400(self, client):
        """Selling shares not held should return 400."""
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "side": "sell", "quantity": 1},
        )
        assert resp.status_code == 400
        assert "Insufficient shares" in resp.json()["detail"]

    def test_unknown_ticker_returns_404(self, client):
        """A ticker not in the price cache should return 404."""
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "ZZZZ", "side": "buy", "quantity": 1},
        )
        assert resp.status_code == 404

    def test_negative_quantity_returns_422(self, client):
        """Negative or zero quantity should return 422 validation error."""
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "side": "buy", "quantity": -1},
        )
        assert resp.status_code == 422

    def test_zero_quantity_returns_422(self, client):
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "side": "buy", "quantity": 0},
        )
        assert resp.status_code == 422

    def test_invalid_side_returns_422(self, client):
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "side": "hold", "quantity": 1},
        )
        assert resp.status_code == 422

    def test_buy_weighted_average_cost(self, client, temp_db):
        """Two buys at different prices should result in a weighted average cost."""
        # Buy 5 at $190
        client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy", "quantity": 5})

        # Update price to $200 and buy 5 more
        price_cache: PriceCache = client.app.state.price_cache
        price_cache.update("AAPL", 200.0)

        client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy", "quantity": 5})

        with get_db(db_path=temp_db) as conn:
            pos = conn.execute(
                "SELECT quantity, avg_cost FROM positions WHERE user_id='default' AND ticker='AAPL'"
            ).fetchone()
            assert pos["quantity"] == pytest.approx(10.0)
            expected_avg = (5 * 190 + 5 * 200) / 10
            assert pos["avg_cost"] == pytest.approx(expected_avg, abs=0.01)


# ---------------------------------------------------------------------------
# Tests: GET /api/portfolio/history
# ---------------------------------------------------------------------------


class TestPortfolioHistory:
    def test_history_returns_list(self, client):
        """History endpoint should return a list (possibly empty)."""
        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_history_contains_snapshots_after_trade(self, client, temp_db):
        """Executing a trade should add a snapshot to history."""
        before = len(client.get("/api/portfolio/history").json())
        client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy", "quantity": 1})
        after = len(client.get("/api/portfolio/history").json())
        assert after > before

    def test_history_snapshots_ordered_ascending(self, client, temp_db):
        """History should be ordered by recorded_at ascending."""
        import uuid
        from datetime import datetime, timedelta

        with get_db(db_path=temp_db) as conn:
            t1 = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
            t2 = datetime.utcnow().isoformat()
            conn.execute(
                "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, 'default', 9000.0, ?)",
                (str(uuid.uuid4()), t1),
            )
            conn.execute(
                "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, 'default', 9500.0, ?)",
                (str(uuid.uuid4()), t2),
            )
            conn.commit()

        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 200
        data = resp.json()
        timestamps = [item["recorded_at"] for item in data]
        assert timestamps == sorted(timestamps)
