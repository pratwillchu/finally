"""SQLite database initialization, connection management, and seed data for FinAlly."""

import os
import sqlite3
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

DB_PATH: str = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(__file__), "../../db/finally.db"),
)

# ---------------------------------------------------------------------------
# Schema (also mirrored to backend/db/schema.sql as a reference copy)
# ---------------------------------------------------------------------------

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

_DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_db(db_path: str | None = None) -> None:
    """Create schema and seed default data. Idempotent — safe to call multiple times."""
    path = db_path or DB_PATH

    # Ensure the parent directory exists
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA_SQL)

        # Seed only when users_profile is empty
        row = conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()
        if row[0] == 0:
            now = datetime.utcnow().isoformat()

            # Default user
            conn.execute(
                "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                ("default", 10000.0, now),
            )

            # Default watchlist
            for ticker in _DEFAULT_TICKERS:
                conn.execute(
                    "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), "default", ticker, now),
                )

            conn.commit()
    finally:
        conn.close()


@contextmanager
def get_db(db_path: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Yield a sqlite3.Connection with row_factory=sqlite3.Row. Closes after use."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()
