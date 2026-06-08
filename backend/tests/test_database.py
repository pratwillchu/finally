"""Unit tests for backend/app/database.py."""

import sqlite3
import uuid
from datetime import datetime

import pytest

from app.database import get_db, init_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.utcnow().isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tables_created(tmp_path):
    """All 6 tables exist after init_db()."""
    db_file = str(tmp_path / "test.db")
    init_db(db_file)

    with get_db(db_file) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {row["name"] for row in rows}

    expected = {
        "users_profile",
        "watchlist",
        "positions",
        "trades",
        "portfolio_snapshots",
        "chat_messages",
    }
    assert expected.issubset(table_names)


def test_seed_data(tmp_path):
    """Default user and 10 watchlist tickers are present after init_db()."""
    db_file = str(tmp_path / "test.db")
    init_db(db_file)

    with get_db(db_file) as conn:
        user = conn.execute(
            "SELECT * FROM users_profile WHERE id='default'"
        ).fetchone()
        assert user is not None
        assert user["cash_balance"] == 10000.0

        tickers = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id='default' ORDER BY ticker"
        ).fetchall()
        ticker_set = {row["ticker"] for row in tickers}

    expected_tickers = {"AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"}
    assert len(ticker_set) == 10
    assert ticker_set == expected_tickers


def test_init_idempotent(tmp_path):
    """Calling init_db() twice does not duplicate seed data."""
    db_file = str(tmp_path / "test.db")
    init_db(db_file)
    init_db(db_file)  # Second call — should be a no-op for seeding

    with get_db(db_file) as conn:
        user_count = conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0]
        watchlist_count = conn.execute(
            "SELECT COUNT(*) FROM watchlist WHERE user_id='default'"
        ).fetchone()[0]

    assert user_count == 1
    assert watchlist_count == 10


def test_unique_constraints(tmp_path):
    """Inserting a duplicate (user_id, ticker) into watchlist raises IntegrityError."""
    db_file = str(tmp_path / "test.db")
    init_db(db_file)

    with get_db(db_file) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                (_uuid(), "default", "AAPL", _now()),
            )
            conn.commit()


def test_positions_crud(tmp_path):
    """Insert, read, update, and delete a position row."""
    db_file = str(tmp_path / "test.db")
    init_db(db_file)

    pos_id = _uuid()
    now = _now()

    with get_db(db_file) as conn:
        # Insert
        conn.execute(
            "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pos_id, "default", "AAPL", 10.0, 150.0, now),
        )
        conn.commit()

        # Read
        row = conn.execute(
            "SELECT * FROM positions WHERE id=?", (pos_id,)
        ).fetchone()
        assert row is not None
        assert row["ticker"] == "AAPL"
        assert row["quantity"] == 10.0
        assert row["avg_cost"] == 150.0

        # Update
        conn.execute(
            "UPDATE positions SET quantity=?, avg_cost=?, updated_at=? WHERE id=?",
            (15.0, 148.0, _now(), pos_id),
        )
        conn.commit()

        updated = conn.execute(
            "SELECT quantity, avg_cost FROM positions WHERE id=?", (pos_id,)
        ).fetchone()
        assert updated["quantity"] == 15.0
        assert updated["avg_cost"] == 148.0

        # Delete
        conn.execute("DELETE FROM positions WHERE id=?", (pos_id,))
        conn.commit()

        deleted = conn.execute(
            "SELECT * FROM positions WHERE id=?", (pos_id,)
        ).fetchone()
        assert deleted is None


def test_trades_append_only(tmp_path):
    """Multiple trade rows can be inserted and counted correctly."""
    db_file = str(tmp_path / "test.db")
    init_db(db_file)

    trades = [
        ("AAPL", "buy", 10.0, 150.0),
        ("AAPL", "sell", 5.0, 160.0),
        ("TSLA", "buy", 3.0, 200.0),
    ]

    with get_db(db_file) as conn:
        for ticker, side, qty, price in trades:
            conn.execute(
                "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_uuid(), "default", ticker, side, qty, price, _now()),
            )
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE user_id='default'"
        ).fetchone()[0]

    assert count == 3


def test_portfolio_snapshots(tmp_path):
    """Snapshot rows can be inserted and queried in time order."""
    db_file = str(tmp_path / "test.db")
    init_db(db_file)

    snapshots = [10000.0, 10250.5, 9875.25, 10500.0]

    with get_db(db_file) as conn:
        for value in snapshots:
            conn.execute(
                "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
                "VALUES (?, ?, ?, ?)",
                (_uuid(), "default", value, _now()),
            )
        conn.commit()

        rows = conn.execute(
            "SELECT total_value FROM portfolio_snapshots WHERE user_id='default' ORDER BY recorded_at"
        ).fetchall()
        values = [row["total_value"] for row in rows]

    assert len(values) == 4
    assert set(values) == set(snapshots)
