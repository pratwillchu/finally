"""Watchlist API routes."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from app.database import get_db
from app.market import PriceCache

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

_TICKER_RE = re.compile(r"^[A-Z0-9]{1,5}$")


class AddTickerRequest(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def ticker_format(cls, v: str) -> str:
        if not _TICKER_RE.match(v):
            raise ValueError("ticker must be 1–5 uppercase alphanumeric characters")
        return v


@router.get("")
async def get_watchlist(request: Request) -> list:
    """Return all watchlist tickers with latest prices from the price cache."""
    price_cache: PriceCache = request.app.state.price_cache

    with get_db() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id='default' ORDER BY added_at ASC"
        ).fetchall()

    result = []
    for row in rows:
        ticker = row["ticker"]
        update = price_cache.get(ticker)
        if update:
            result.append(
                {
                    "ticker": ticker,
                    "price": update.price,
                    "daily_change_pct": update.change_percent,
                    "direction": update.direction,
                }
            )
        else:
            result.append(
                {
                    "ticker": ticker,
                    "price": None,
                    "daily_change_pct": 0,
                    "direction": "unchanged",
                }
            )

    return result


@router.post("", status_code=201)
async def add_ticker(request: Request, body: AddTickerRequest) -> dict:
    """Add a ticker to the watchlist.

    Validates format, checks for duplicates, then starts price tracking.
    """
    ticker = body.ticker

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM watchlist WHERE user_id='default' AND ticker=?", (ticker,)
        ).fetchone()

        if existing:
            raise HTTPException(status_code=422, detail=f"Ticker {ticker!r} is already in the watchlist")

        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, 'default', ?, ?)",
            (str(uuid.uuid4()), ticker, now),
        )
        conn.commit()

    # Start price generation for the new ticker
    market_source = request.app.state.market_source
    await market_source.add_ticker(ticker)

    return {"ticker": ticker}


@router.delete("/{ticker}", status_code=204)
async def remove_ticker(ticker: str, request: Request) -> Response:
    """Remove a ticker from the watchlist and stop price tracking."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM watchlist WHERE user_id='default' AND ticker=?", (ticker,)
        ).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail=f"Ticker {ticker!r} not found in watchlist")

        conn.execute(
            "DELETE FROM watchlist WHERE user_id='default' AND ticker=?", (ticker,)
        )
        conn.commit()

    # Stop price generation for the removed ticker
    market_source = request.app.state.market_source
    await market_source.remove_ticker(ticker)

    return Response(status_code=204)
