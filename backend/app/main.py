"""FinAlly FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router
from app.api.portfolio import router as portfolio_router
from app.api.watchlist import router as watchlist_router
from app.database import get_db, init_db
from app.market import PriceCache, create_market_data_source, create_stream_router

# Load .env from project root (two levels up from backend/app/)
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

logger = logging.getLogger(__name__)

# Import chat router — created by the LLM engineer; may not exist yet during dev
try:
    from app.api.chat import router as chat_router  # type: ignore[import]

    HAS_CHAT = True
except ImportError:
    HAS_CHAT = False
    chat_router = None

# Create price_cache at module level so it can be referenced by the stream router
# before the lifespan has run.
price_cache = PriceCache()


async def _snapshot_loop(app: FastAPI) -> None:
    """Background task: record a portfolio snapshot every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        try:
            _cache: PriceCache = app.state.price_cache
            with get_db() as conn:
                profile = conn.execute(
                    "SELECT cash_balance FROM users_profile WHERE id='default'"
                ).fetchone()
                cash = profile["cash_balance"] if profile else 0.0

                rows = conn.execute(
                    "SELECT ticker, quantity FROM positions WHERE user_id='default'"
                ).fetchall()

                total = cash
                for row in rows:
                    p = _cache.get_price(row["ticker"])
                    if p:
                        total += row["quantity"] * p

                now = datetime.utcnow().isoformat()
                conn.execute(
                    "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
                    "VALUES (?, 'default', ?, ?)",
                    (str(uuid.uuid4()), total, now),
                )
                conn.commit()
        except Exception as exc:
            logger.warning("Snapshot error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of background services."""
    # Initialize DB (creates tables + seeds data if needed)
    init_db()

    # Create market data source and start it with the current watchlist
    market_source = create_market_data_source(price_cache)

    with get_db() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id='default'"
        ).fetchall()
        tickers = [row["ticker"] for row in rows]

    await market_source.start(tickers)

    # Record an initial snapshot so the P&L chart has a baseline from first launch
    try:
        with get_db() as conn:
            now = datetime.utcnow().isoformat()
            conn.execute(
                "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
                "VALUES (?, 'default', 10000.0, ?)",
                (str(uuid.uuid4()), now),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("Initial snapshot error: %s", exc)

    # Store in app state so routes can access them
    app.state.price_cache = price_cache
    app.state.market_source = market_source

    # Start background snapshot task
    task = asyncio.create_task(_snapshot_loop(app))

    yield  # App serves requests here

    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await market_source.stop()


app = FastAPI(title="FinAlly — AI Trading Workstation", lifespan=lifespan)

# Register routers
app.include_router(create_stream_router(price_cache))
app.include_router(health_router)
app.include_router(portfolio_router)
app.include_router(watchlist_router)

if HAS_CHAT and chat_router is not None:
    app.include_router(chat_router)

# Mount static frontend (only when the Next.js export exists)
_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
