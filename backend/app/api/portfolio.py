"""Portfolio API routes: positions, trade execution, and portfolio history."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.database import get_db
from app.market import PriceCache

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TradeRequest(BaseModel):
    ticker: str
    side: str
    quantity: float

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be greater than 0")
        return v

    @field_validator("side")
    @classmethod
    def side_must_be_valid(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        return v


# ---------------------------------------------------------------------------
# Standalone execute_trade — importable by the LLM engineer
# ---------------------------------------------------------------------------


def execute_trade(
    conn: sqlite3.Connection,
    ticker: str,
    side: str,
    quantity: float,
    price_cache: PriceCache,
) -> dict:
    """Execute a trade against the database.

    Returns a trade dict on success. Raises HTTPException on validation failure.
    This function is intentionally importable by the chat/LLM module.
    """
    current_price = price_cache.get_price(ticker)
    if current_price is None:
        raise HTTPException(status_code=404, detail=f"No price available for ticker {ticker!r}")

    now = datetime.utcnow().isoformat()
    trade_id = str(uuid.uuid4())

    if side == "buy":
        cost = quantity * current_price
        profile = conn.execute(
            "SELECT cash_balance FROM users_profile WHERE id='default'"
        ).fetchone()
        cash = profile["cash_balance"]

        if cash < cost:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient cash: need ${cost:.2f}, have ${cash:.2f}",
            )

        # Deduct cash
        conn.execute(
            "UPDATE users_profile SET cash_balance = cash_balance - ? WHERE id='default'",
            (cost,),
        )

        # Upsert position (weighted average cost)
        existing = conn.execute(
            "SELECT id, quantity, avg_cost FROM positions WHERE user_id='default' AND ticker=?",
            (ticker,),
        ).fetchone()

        if existing:
            old_qty = existing["quantity"]
            old_avg = existing["avg_cost"]
            new_qty = old_qty + quantity
            new_avg = (old_qty * old_avg + quantity * current_price) / new_qty
            conn.execute(
                "UPDATE positions SET quantity=?, avg_cost=?, updated_at=? "
                "WHERE user_id='default' AND ticker=?",
                (new_qty, new_avg, now, ticker),
            )
        else:
            conn.execute(
                "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                "VALUES (?, 'default', ?, ?, ?, ?)",
                (str(uuid.uuid4()), ticker, quantity, current_price, now),
            )

    elif side == "sell":
        existing = conn.execute(
            "SELECT id, quantity, avg_cost FROM positions WHERE user_id='default' AND ticker=?",
            (ticker,),
        ).fetchone()

        if not existing or existing["quantity"] < quantity:
            held = existing["quantity"] if existing else 0.0
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient shares: trying to sell {quantity}, have {held}",
            )

        proceeds = quantity * current_price
        conn.execute(
            "UPDATE users_profile SET cash_balance = cash_balance + ? WHERE id='default'",
            (proceeds,),
        )

        new_qty = existing["quantity"] - quantity
        if new_qty == 0:
            conn.execute(
                "DELETE FROM positions WHERE user_id='default' AND ticker=?", (ticker,)
            )
        else:
            conn.execute(
                "UPDATE positions SET quantity=?, updated_at=? "
                "WHERE user_id='default' AND ticker=?",
                (new_qty, now, ticker),
            )

    # Record trade
    conn.execute(
        "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
        "VALUES (?, 'default', ?, ?, ?, ?, ?)",
        (trade_id, ticker, side, quantity, current_price, now),
    )

    # Record portfolio snapshot immediately after trade
    _record_snapshot(conn, price_cache, now)

    conn.commit()

    return {
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": current_price,
        "executed_at": now,
    }


def _record_snapshot(
    conn: sqlite3.Connection,
    price_cache: PriceCache,
    timestamp: str | None = None,
) -> None:
    """Record a portfolio_snapshots row with the current total value."""
    now = timestamp or datetime.utcnow().isoformat()
    profile = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE id='default'"
    ).fetchone()
    cash = profile["cash_balance"] if profile else 0.0

    positions = conn.execute(
        "SELECT ticker, quantity FROM positions WHERE user_id='default'"
    ).fetchall()

    total = cash
    for row in positions:
        price = price_cache.get_price(row["ticker"])
        if price:
            total += row["quantity"] * price

    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
        "VALUES (?, 'default', ?, ?)",
        (str(uuid.uuid4()), total, now),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def get_portfolio(request: Request) -> dict:
    """Return current cash balance, positions with unrealized P&L, and total value."""
    price_cache: PriceCache = request.app.state.price_cache

    with get_db() as conn:
        profile = conn.execute(
            "SELECT cash_balance FROM users_profile WHERE id='default'"
        ).fetchone()
        cash = profile["cash_balance"] if profile else 0.0

        rows = conn.execute(
            "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id='default'"
        ).fetchall()

    positions = []
    positions_value = 0.0

    for row in rows:
        ticker = row["ticker"]
        qty = row["quantity"]
        avg_cost = row["avg_cost"]
        current_price = price_cache.get_price(ticker)

        if current_price is None:
            current_price = avg_cost  # Fall back to cost if no price yet

        unrealized_pnl = (current_price - avg_cost) * qty
        pnl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost else 0.0
        positions_value += current_price * qty

        positions.append(
            {
                "ticker": ticker,
                "quantity": qty,
                "avg_cost": round(avg_cost, 4),
                "current_price": round(current_price, 4),
                "unrealized_pnl": round(unrealized_pnl, 4),
                "pnl_pct": round(pnl_pct, 4),
            }
        )

    total_value = cash + positions_value

    return {
        "cash_balance": round(cash, 4),
        "total_value": round(total_value, 4),
        "positions": positions,
    }


@router.post("/trade")
async def trade(request: Request, body: TradeRequest) -> dict:
    """Execute a market order (buy or sell)."""
    price_cache: PriceCache = request.app.state.price_cache

    with get_db() as conn:
        return execute_trade(conn, body.ticker, body.side, body.quantity, price_cache)


@router.get("/history")
async def portfolio_history(request: Request) -> list:
    """Return portfolio value snapshots ordered by time ascending."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT total_value, recorded_at FROM portfolio_snapshots "
            "WHERE user_id='default' ORDER BY recorded_at ASC"
        ).fetchall()

    return [{"total_value": row["total_value"], "recorded_at": row["recorded_at"]} for row in rows]
