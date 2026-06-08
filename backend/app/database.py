"""SQLite database initialization, schema, and connection management."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# DB path: backend/db/finally.db (relative to project root is db/finally.db)
# In Docker the volume is mounted at /app/db, which maps to backend/db at runtime.
_HERE = Path(__file__).parent.parent  # backend/
DB_PATH = str(_HERE / "db" / "finally.db")

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

_SCHEMA_SQL = """
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
"""


def _seed_db(conn: sqlite3.Connection) -> None:
    """Insert default data if tables are empty."""
    now = datetime.utcnow().isoformat()

    # Seed user profile if not present
    existing = conn.execute("SELECT id FROM users_profile WHERE id='default'").fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO users_profile (id, cash_balance, created_at) VALUES ('default', 10000.0, ?)",
            (now,),
        )

    # Seed default watchlist entries
    for ticker in DEFAULT_TICKERS:
        exists = conn.execute(
            "SELECT id FROM watchlist WHERE user_id='default' AND ticker=?", (ticker,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, 'default', ?, ?)",
                (str(uuid.uuid4()), ticker, now),
            )

    conn.commit()


def init_db(db_path: str | None = None) -> None:
    """Create tables and seed default data if needed.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.
    """
    path = db_path or DB_PATH
    # Ensure directory exists
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA_SQL)
        _seed_db(conn)
    finally:
        conn.close()


@contextmanager
def get_db(db_path: str | None = None):
    """Context manager yielding an sqlite3.Connection with row_factory=sqlite3.Row.

    Usage:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM watchlist").fetchall()
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrent read/write performance
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()
