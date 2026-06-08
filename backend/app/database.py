"""SQLite database management for FinAlly.

Provides lazy initialization: creates schema and seeds default data
if the database file doesn't exist or tables are missing.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# Default DB path — can be overridden via DB_PATH env var or init_db(path)
_DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "db" / "finally.db"

_db_path: Path | None = None


def get_db_path() -> Path:
    """Return the active database path."""
    if _db_path is not None:
        return _db_path
    env_path = os.environ.get("DB_PATH")
    if env_path:
        return Path(env_path)
    return _DEFAULT_DB_PATH


def init_db(path: Path | str | None = None) -> Path:
    """Initialize the database at the given path (or default).

    Creates tables and seeds default data if the database is new.
    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.

    Returns the path used.
    """
    global _db_path
    if path is not None:
        _db_path = Path(path)
    db = get_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        _create_schema(conn)
        _seed_data(conn)
        conn.commit()
    finally:
        conn.close()

    return db


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users_profile (
            id TEXT PRIMARY KEY,
            cash_balance REAL NOT NULL DEFAULT 10000.0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            ticker TEXT NOT NULL,
            added_at TEXT NOT NULL,
            UNIQUE(user_id, ticker)
        );

        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            ticker TEXT NOT NULL,
            quantity REAL NOT NULL,
            avg_cost REAL NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, ticker)
        );

        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            executed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            total_value REAL NOT NULL,
            recorded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            actions TEXT,
            created_at TEXT NOT NULL
        );
    """)


_DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def _seed_data(conn: sqlite3.Connection) -> None:
    """Seed default user and watchlist if not already present."""
    now = datetime.utcnow().isoformat()

    # Seed default user profile
    conn.execute(
        "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
        ("default", 10000.0, now),
    )

    # Seed default watchlist
    for ticker in _DEFAULT_TICKERS:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, 'default', ?, ?)",
            (str(uuid.uuid4()), ticker, now),
        )


@contextmanager
def get_db():
    """Context manager that yields a sqlite3.Connection.

    Usage:
        with get_db() as conn:
            rows = conn.execute("SELECT ...").fetchall()
    """
    db = get_db_path()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()
